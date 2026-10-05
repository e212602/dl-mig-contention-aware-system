import os
import subprocess
import yaml
import csv

def load_test_config(config_path: str) -> dict:
    """Load Yaml Config file."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read the test config file.") from exc

    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    if not isinstance(config, dict):
        raise TypeError(f"Expected a mapping in {config_path}")

    return config


def create_kubectl_cmd(config: str):
    """Create pods based on the provided configuration."""
    if not os.path.exists(config):
        raise FileNotFoundError(f"Config file not found: {config}")

    r = subprocess.run(["kubectl", "create", "-f", config], capture_output=True, text=True, check=True)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create pods: {r.stderr}")


def delete_kubectl_cmd(reasource: str):
    """Delete pods based on the provided resource name."""
    r = subprocess.run(["kubectl", "delete", reasource], capture_output=True, text=True, check=True)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to delete resource: {r.stderr}")

def kube_res_wait_for_completion(resource: str):
    """Check if the specified resource has completed. """
    r = subprocess.run(["kubectl", "wait", "--for=condition=complete", resource, "--timeout=1000s"], capture_output=True, text=True, check=True)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to wait for resource completion: {r.stderr}")
    if "condition met" in r.stdout:
        return True
    
    return False



def set_fields_in_yaml(yaml_path: str, config: str) -> None:
    with open(yaml_path, "w") as f:
        yaml.dump(config, f)


def report_results_to_csv(resource: str, specs: str, csv_path: str) -> None:
    """Write Start, Completion, and Specs of the Job to a CSV file."""
    with open(csv_path, mode='a', newline='') as csv_file:
        fieldnames = ['ResName', 'Start', 'Completion', 'Specs']
        r = subprocess.run(["kubectl", "get", "job", resource, "-o", "custom-columns=NAME:.metadata.name,START:.status.startTime,COMPLETE:.status.completionTime"], capture_output=True, text=True, check=True)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to get job details: {r.stderr}")
        lines = r.stdout.strip().splitlines()
        if len(lines) < 2:
            raise RuntimeError(f"No job details found for resource: {resource}")
        name, start, complete = lines[1].split()
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writerow({'ResName': name, 'Start': start, 'Completion': complete, 'Specs': specs})

