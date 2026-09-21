import argparse as ap
import copy
import itertools
import subprocess

from utils import (
    create_kubectl_cmd,
    delete_kubectl_cmd,
    kube_res_wait_for_completion,
    load_test_config,
    report_results_to_csv,
    set_fields_in_yaml,
)

MODEL_MEMORY_GI = {
    "bigscience/bloom-1b1": 32,
    "EleutherAI/pythia-160m": 16,
    "Qwen/Qwen2.5-0.5B": 16,
    "EleutherAI/pythia-1b": 32,
}

DEEPSPEED_MODELS = [
    "bigscience/bloom-1b1",
    # "EleutherAI/pythia-160m",
    # "Qwen/Qwen2.5-0.5B",
    # "EleutherAI/pythia-1b",
]

JOB_TEMPLATE = {
    "apiVersion": "batch/v1",
    "kind": "Job",
    "metadata": {"name": "PLACEHOLDER"},
    "spec": {
        "parallelism": 1,
        "template": {
            "spec": {
                "containers": [
                    {
                        "command": [
                            "/bin/bash",
                            "-c",
                            (
                                "#!/bin/bash\n"
                                "export DS_SDMA_ALLGATHER=0\n"
                                "export TORCH_EXTENSIONS_DIR=/tmp/torch_extensions\n"
                                "export DS_SKIP_CUDA_CHECK=1\n"
                                "export PYTORCH_HIP_ALLOC_CONF=expandable_segments:True\n"
                                "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True\n"
                                "export TORCH_NCCL_ENABLE_MONITORING=0\n"
                                'python "train_qwen3_zero3.py" '
                                '--model_name "${MODEL:-PLACEHOLDER}" '
                                '--ds_config "${DS_CONFIG:-ds_config_zero3.json}"\n'
                            ),
                        ],
                        "image": "e8113/deepspeed:v1",
                        "imagePullPolicy": "Never",
                        "name": "PLACEHOLDER",
                        "env": [{"name": "MODEL", "value": "PLACEHOLDER"}],
                        "resources": {
                            "limits": {
                                "cpu": "5",
                                "memory": "8Gi",
                                "nvidia.com/gpu": 1,
                            }
                        },
                        "volumeMounts": [
                            {
                                "name": "hf-cache",
                                "mountPath": "/home/deepspeed/.cache/huggingface",
                            }
                        ],
                        "stdin": True,
                        "tty": True,
                    }
                ],
                "volumes": [
                    {
                        "name": "hf-cache",
                        "hostPath": {
                            "path": "/home/ubuntu/.cache/huggingface",
                            "type": "Directory",
                        },
                    }
                ],
                "restartPolicy": "Never",
            }
        },
    },
}


def sanitize_name(text: str) -> str:
    """Make a string safe for use as a k8s resource name segment."""
    return text.lower().replace("/", "-").replace(".", "-").replace("_", "-")


def get_unique_counts_itertools(arr):
    # Returns combinations of length equal to input array length
    return list(itertools.combinations_with_replacement(arr, len(arr)))


def build_job_manifest(round_idx: int, job_idx: int, model_name: str):
    """Return (job_name, manifest_dict, yaml_path) for a single job."""
    model_slug = sanitize_name(model_name)
    job_name = f"ops-round{round_idx}-job{job_idx}-{model_slug}"

    manifest = copy.deepcopy(JOB_TEMPLATE)
    manifest["metadata"]["name"] = job_name
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    container["name"] = job_name
    container["env"][0]["value"] = model_name

    memory_gi = MODEL_MEMORY_GI.get(model_name)
    if memory_gi is None:
        print(f"Warning: no memory mapping for model '{model_name}', "
              f"falling back to template default")
    else:
        container["resources"]["limits"]["memory"] = f"{memory_gi}Gi"

    yaml_path = f"./ops/{job_name}.yaml"
    return job_name, manifest, yaml_path


def collect_pod_logs(job_name: str) -> str:
    """Fetch logs for all pods belonging to a job, concatenated."""
    log_chunks = [f"===== Logs for job: {job_name} ====="]
    try:
        r = subprocess.run(
            ["kubectl", "get", "pods", "-l", f"job-name={job_name}",
             "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, check=True,
        )
        pod_names = r.stdout.split()
        if not pod_names:
            log_chunks.append("(no pods found)")
        for pod in pod_names:
            log_chunks.append(f"--- Pod: {pod} ---")
            try:
                lr = subprocess.run(
                    ["kubectl", "logs", pod],
                    capture_output=True, text=True, check=True,
                )
                log_chunks.append(lr.stdout)
            except subprocess.CalledProcessError as e:
                log_chunks.append(f"(failed to fetch logs: {e.stderr})")
    except subprocess.CalledProcessError as e:
        log_chunks.append(f"(failed to list pods: {e.stderr})")

    return "\n".join(log_chunks) + "\n"


def mig_1g_6gb_deepspeed_combo():
    combos = get_unique_counts_itertools(DEEPSPEED_MODELS)
    print(f"Total rounds to run: {len(combos)}")

    for round_idx, combo in enumerate(combos, start=1):
        print(f"\n=== Round {round_idx}/{len(combos)}: {combo} ===")

        job_infos = []  # (job_name, model_name)

        # 1. Launch all 4 jobs in parallel
        for job_idx, model_name in enumerate(combo):
            job_name, manifest, yaml_path = build_job_manifest(round_idx, job_idx, model_name)
            set_fields_in_yaml(yaml_path, manifest)
            try:
                create_kubectl_cmd(yaml_path)
                print(f"Launched job {job_name} (model={model_name})")
                job_infos.append((job_name, model_name))
            except Exception as e:
                print(f"Failed to launch job {job_name}: {e}")

        # 2. Wait for each job (individually; they're already running concurrently)
        for job_name, model_name in job_infos:
            resource = f"job/{job_name}"
            try:
                if kube_res_wait_for_completion(resource):
                    print(f"Job completed successfully: {job_name}")
                else:
                    print(f"Job did not complete successfully: {job_name}")
            except Exception as e:
                print(f"Error waiting on job {job_name}: {e}")

        # 3. Collect logs for all jobs in this round BEFORE deleting
        round_log_path = f"round_{round_idx}_log_collection.log"
        with open(round_log_path, "w") as log_file:
            for job_name, model_name in job_infos:
                log_file.write(collect_pod_logs(job_name))
                log_file.write("\n")
        print(f"Logs written to {round_log_path}")

        # 4. Report results to CSV for each job
        for job_idx, (job_name, model_name) in enumerate(job_infos):
            specs = f"round_{round_idx}_job_{job_idx}_{sanitize_name(model_name)}"
            try:
                report_results_to_csv(job_name, specs, "./results.csv")
            except Exception as e:
                print(f"Failed to report results for job {job_name}: {e}")

        # 5. Cleanup: delete all jobs in this round
        for job_name, model_name in job_infos:
            try:
                delete_kubectl_cmd(f"job/{job_name}")
            except Exception as e:
                print(f"Failed to delete job {job_name}: {e}")


def mig_1g_6gb_all_ops():
    # Load the test configuration
    config = load_test_config("./ops/ops.yaml")
    print(f"Parallelism: {config.get('spec', 'spec: Not specified').get('parallelism', 'Not specified')})")
    parallelism_list = [1, 2, 3, 4]
    for p in parallelism_list:
        print(f"Running with parallelism: {p}")
        config['spec']['parallelism'] = p
        set_fields_in_yaml("./ops/ops.yaml", config)
        create_kubectl_cmd("./ops/ops.yaml")
        if kube_res_wait_for_completion("job/ops"):
            print(f"Job completed successfully with parallelism: {p}")
        else:
            print(f"Job did not complete successfully with parallelism: {p}")
        report_results_to_csv("ops", f"mig_1g.6gb_parallelism_{p}", "./results.csv")
        delete_kubectl_cmd("job/ops")


def mig_1g_6gb_sequential():
    """Run each DeepSpeed model exclusively, one after another (4 total executions)."""
    print(f"Total executions to run: {len(DEEPSPEED_MODELS)}")

    for idx, model_name in enumerate(DEEPSPEED_MODELS, start=1):
        print(f"\n=== Execution {idx}/{len(DEEPSPEED_MODELS)}: {model_name} ===")

        # 1. Launch the single job for this model
        job_name, manifest, yaml_path = build_job_manifest(idx, 0, model_name)
        set_fields_in_yaml(yaml_path, manifest)

        try:
            create_kubectl_cmd(yaml_path)
            print(f"Launched job {job_name} (model={model_name})")
        except Exception as e:
            print(f"Failed to launch job {job_name}: {e}")
            continue

        # 2. Wait for it to finish before moving to the next model (exclusive execution)
        resource = f"job/{job_name}"
        try:
            if kube_res_wait_for_completion(resource):
                print(f"Job completed successfully: {job_name}")
            else:
                print(f"Job did not complete successfully: {job_name}")
        except Exception as e:
            print(f"Error waiting on job {job_name}: {e}")

        # 3. Report start/end time to the console
        try:
            r = subprocess.run(
                ["kubectl", "get", "job", job_name, "-o",
                 "custom-columns=START:.status.startTime,COMPLETE:.status.completionTime"],
                capture_output=True, text=True, check=True,
            )
            lines = r.stdout.strip().splitlines()
            if len(lines) >= 2:
                start, complete = lines[1].split()
                print(f"Start: {start}  |  Completion: {complete}")
            else:
                print("Start/completion time not available yet.")
        except Exception as e:
            print(f"Failed to fetch start/end time for job {job_name}: {e}")

        # 4. Collect and write logs for this execution
        log_path = f"execution_{idx}_{sanitize_name(model_name)}_log.log"
        with open(log_path, "w") as log_file:
            log_file.write(collect_pod_logs(job_name))
        print(f"Logs written to {log_path}")

        # 5. Report results to CSV (also records Start/Completion)
        specs = f"execution_{idx}_{sanitize_name(model_name)}_execlusive"
        try:
            report_results_to_csv(job_name, specs, "./results.csv")
        except Exception as e:
            print(f"Failed to report results for job {job_name}: {e}")

        # 6. Cleanup before the next execution starts
        try:
            delete_kubectl_cmd(resource)
        except Exception as e:
            print(f"Failed to delete job {job_name}: {e}")

test_map = {
    'mig_1g.6gb_all_ops': mig_1g_6gb_all_ops,
    'mig_1g.6gb_deepspeed_combo': mig_1g_6gb_deepspeed_combo,
    'mig_1g.6gb_sequential': mig_1g_6gb_sequential,
}


def list_all_tests():
    print("Available tests:")
    for test_name in test_map:
        print(f" - {test_name}")


def main():
    parser = ap.ArgumentParser(description="Run workload tests.")
    parser.add_argument("--test_name", type=str, nargs='?', default='mig_1g.6gb_all_ops', help="Name of the test to run.")
    parser.add_argument("--help-list-tests", help="List all available tests.", action="store_true")
    args = parser.parse_args()

    if args.help_list_tests:
        list_all_tests()
        return

    if args.test_name not in test_map:
        print(f"Error: Test '{args.test_name}' not found.")
        list_all_tests()
        return

    print(f"Running test: {args.test_name}")
    test_map[args.test_name]()


if __name__ == "__main__":
    main()