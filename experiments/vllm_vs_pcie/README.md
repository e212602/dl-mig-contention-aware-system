# vllm_vs_pcie

This Ansible experiment measures each model in `workload/vllm/model_Server/`
while one, two, or three PCIe stress Jobs run alongside it. The SILP controller
uses a per-worker allocation file: the vLLM worker receives `bw` GB/s and each
stress worker receives `bw_pcie_stress` GB/s.

The default sweep contains 8 model-bearing manifests x 5 vLLM bandwidths x 3
stress-worker counts x 5 stress bandwidths = 600 iterations. The generic
`service_vllm.yaml` is not a model-bearing manifest and is not included.

## Run

Run from this directory with an Ansible inventory that contains the hostnames
exported as `SERVER_ID` and `CLIENT_ID`:

```sh
export SERVER_ID=<kubernetes-server-inventory-host>
export CLIENT_ID=<aiperf-client-inventory-host>
ansible-playbook -i <inventory> vllm_vs_pcie.yml
```

The client needs `aiperf` in the directory containing its configured
`ansible_python_interpreter`. The server needs `kubectl`, Go-compatible Linux
access to Kubernetes, the `kubernetes.core` Ansible collection, the configured
vLLM/HF cache and HAMi-core library paths, and an accessible Prometheus service.
The client must be able to reach the model ingress at `localhost:8080` (for
example, through the SSH tunnel used by the other experiments).

Model runtime settings are copied from the model-bearing manifests and
normalized in `vllm_vs_pcie_vars.yml` so the rate-control mounts and labels can
be added without editing those source files. The experiment uses a run-specific
Ingress path and Kubernetes resource names to avoid colliding with existing
vLLM resources. Adjust the host paths and workload settings there if the target
hosts differ.

Results are written below `results/` in this directory, one folder per model
and bandwidth/worker-count combination. The experiment uses run-specific
numeric rate-control worker IDs and allocation filenames to avoid clobbering
other runs' controller state.
