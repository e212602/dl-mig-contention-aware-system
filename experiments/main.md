# Architecture
![alt text](./figures/architecture-1.png)

# CPU and RAM Stress
```
apiVersion: v1
kind: Pod
metadata:
  name: ram-bandwidth-stress
  labels:
    app.kubernetes.io/name: ram-bandwidth-stress
spec:
  # Never restart: a restart would re-run apt-get and silently interrupt the load.
  restartPolicy: Never
  terminationGracePeriodSeconds: 5
  # Must share a node with the vLLM pods, otherwise there is no memory contention.
  # Matches any pod that belongs to a Job; narrow the selector if other Jobs exist.
  affinity:
    podAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - topologyKey: kubernetes.io/hostname
          labelSelector:
            matchExpressions:
              - key: job-name
                operator: Exists
  containers:
    - name: stress
      image: debian:bookworm-slim
      command: ["/bin/sh", "-c"]
      args:
        - |
          set -e
          apt-get update -qq
          apt-get install -y -qq stress-ng procps
          exec stress-ng --stream 4 --timeout 3h
      # Ready only once stress-ng is actually running (not just when the container started).
      readinessProbe:
        exec:
          command: ["pgrep", "-x", "stress-ng"]
        periodSeconds: 5
        failureThreshold: 120
      resources:
        requests:
          cpu: "4"
          memory: "8Gi"
        limits:
          cpu: "4"
          memory: "8Gi"
```
![alt text](./figures/ram_bandwidth_stress_1v1_request_rate_output_throughput.png)
![alt text](./figures/ram_bandwidth_stress_1v1_request_rate_request_throughput.png)
![alt text](./figures/ram_bandwidth_stress_1v1_cpu_usage_cpuoffload-on.png)

# PCIe Stress Test (Rate Control Verification)

![alt text](./figures/pcie_stress_baseline_vs_ctrl_bw_baseline_vs_ctrl_bw_rate_%5B1,%202%5D_workers_bandwidth.png)
![alt text](./figures/pcie_stress_baseline_vs_ctrl_bw_baseline_vs_ctrl_bw_rate_%5B1,%202%5D_workers_latency.png)
![alt text](./figures/pcie_stress_baseline_vs_ctrl_bw_baseline_vs_ctrl_bw_rate_%5B1,%202,%203,%204%5D_workers_bandwidth.png)
![alt text](./figures/pcie_stress_baseline_vs_ctrl_bw_baseline_vs_ctrl_bw_rate_%5B1,%202,%203,%204%5D_workers_latency.png)


