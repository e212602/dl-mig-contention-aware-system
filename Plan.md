# Summary:
This repository implements a GPU single node system designed for optimizing MIG collocation of deep learning training tasks in a multi-tenant system with the capability of being contention aware.

# Target Workload:
small-to-mid sized models implemented for distillation or parameter-efficient fine tuning
* What dataset will be used ? (High Priority)

# Related Work:
* What are adding as a feature that current tools/research proposals does not have ? (High Priority)

1- TGS: 
TGS employs a dynamic system that controls the rate at which kernels from production and opportunistic jobs. The system monitors the kernel arrival rate for both type of jobs, and mitigates contention by adjusting the output kernel flow rate of opportunistic prioritizing the rate flow of production jobs.

Dataset:
- A combination of low- and high-contention training models (ResNet-50, Base-Bert, ShuffleNet, MobileNet, GCN, DLRM, and ESPnet2)

Comparison:
- TGS (Proposal), Exclusive, MIG, MPS, Co-execution.
* One problem with MIG and MPS is that the setting is done manually by experimenting the best configuration.

Setup:
- 2xA100.40gb 

Methodology:
- Adaptive Rate Control (AIMD):
* alpha and beta -----> number of thread-blocks per time period (However, this number might be intrinsically low for some kernels, which subsequently results in a decreased rates) + Requires interrupting the critical execution path for reading number of blocks for each cudaLaunch API call.

* Points to consider:
- We can target the problem where multiple tenants share the same subscription (no discrimination in terms of opportunistic or production) [Weak]
- The way contention is determined using number of threads-block seems sketchy as this number differs across kernels [CHECK]
- With TGS the action is determined via comparing rate against thresholds, but these thresholds are manually tuned. [Weak]
- Is there specific models in the category of opportunistic jobs that suffers the most with TGS ? [CHECK]
- TGS is mostly effective when jobs can be categorized into production and opportunistic.
- Can we integrate the contention detection methodology of TGS into MIG PCIE contention ?


2- PCIe Bandwidth-Aware Scheduling for Multi-Instance GPUs
The authors studied the relation between the PCIe contention and its impact on the runtime of each deep learning inference job in MIG multi-tenant environment. The authors modeled slowdown as a linear function of the ratio of pcie demand to uniformly distributed maximum bandwidth across all tenants. Using their modeling, a contention is detected once the ratio of pcie demand to available bandwidth is larger than unity. For detecting contention, the individual demand of each job must be known. Acquiring the demand of each requires expensive profiling process, yet the authors reduces the profiling cost suggesting that jobs running the same application with different parameters share the same characteristics.  

* Workload:
- Bloom560m powered using ZeRO-Inference (pcie-bound-job)
- Resnet50 (non-pcie-bound jobs)

* Weak points:
- Linear modeling of slowdown and pcie contention.
- Assuming a static pcie demand for jobs
- Requires profiling to infer pcie demand

3- Baymax:
The authors targeted the prolonged latency when collocating throughput oriented jobs with user-facing applications. In addition to the delay caused by kernels battling for acquiring access to GPU, the contention on PCIe developed by concurrently running jobs slows the runtime of less pcie-bound jobs severely. To mitigate the delay caused by PCIe contention, the authors constrained the number of throughput oriented tasks such that the effective PCIe bandwidth is larger than the total bandwidth required by these tasks. 

* Weak Points:
- Requires profiling to acquire bandwidth


4- Elastic MIG Reconfiguration with PCIe-Aware Placement for Multi-Tenant GPUs
The authors proposed a system that can identify the source of slowdown and takes an action that increases the isolation of a tenant in a multi-tenant environment. To detect PCIe contention, the authors monitors the PCIe usage and IO pressure periodically. If contention is detected, proposed system applies I/O throttle on the tenant causing the contention.

Workload:
- Inference LLM tasks.

5- 

# Questions to raise:
- Mixing training and interference vs pure training ?
- fine-grained Multiplexing vs coarse-grained partitioning ?
- Training environment: is there a well-established system to adapt ? containerized vs HPC vs plain processes ?
- Workload: Is there a reference dataset ?
- Do we need to profile jobs ? Assume our methodology does not require profiling, how do we compare our solution to others which requires profiling ?
- Comprising privacy of jobs by intercepting their kernels, do we need it?
- From the Bymax paper, we notice a discrepancy between expectation and observations in terms of pcie contention, e.g. resnet (0.15GB/s) + bert (0.05GB/s) given pcie bandwidth is uniformly partitioned then each gets 100GB/s which is more than what each application needs, so why do we observe contention ?


# Motivation:
NVIDIA MIG partitioning ensures isolating SM units and memory in a among jobs in a multi-tenant environment. However, the PCIe link connecting the host and GPU remains a shared component. Therefore, collocated throughput oriented tasks experience severe slowdown in performance due PCIe contention. To verify this claim we setup the following experimental setup:

* Workload:
Most of the relevant works were focusing on collocating a throughput oriented job (training task) with a latency critical one (inference). Yet, we will only focus on experiment with training tasks in one of the following systems:
1- Hyperparameter tuning: (Same workload with different hyperparameter configurations)
2- Parameter-efficient fine-tuning (e.g. LoRA): (Same/different model/s trained on a downstream task)
3- Training Small-to-mid sized models on a single GPU: (different models trained from scratch, but they fit into a single GPU)

* System Setup:
1- Bootstrap kubernetes environment (Containerized workload).
2- Workload generator ---> Scheduler ----> GPU
                                ↑            |
                                |            ↓
                                <---------Monitor

* Components:
1- Workload Generator:
2- Scheduler
3- Monitor
4- GPU

* Limitations:
- Current Max PCIe bandwidth for pinned memory is 22-23GB/s and for pageable it is 10-15GB/sec




# Realizations:
1- Contention is not only coming from pcie, but also from the cpu

# Testbed:



# Testbed Notes:
- For computer vision models (bs=32, num-workers=1, cpu=4, ram=4Gi, gpu=2g.12gb), no contention is observed when running with number of workers of dataloader is set to 1. This confirms that the previously observed contention is not caused by PCIe, but probably by CPU processing given that the ram usage for both were relatively low.
- 


# Kubernetes Resource limitation notes:
- Kubeflow failed with mix gpu provisioning
- CPU limitation only limits the time the pod uses the cpu; it does isolate the cores.


# Homogeneous Training Targeted Workload:
| Workload  | MiG Config | Contention Y/N | Note |
| ------------- | ------------- | ------------- | ------------- |
| EleutherAI/pythia-1b  | 1g.6gb  | Y | |
| Qwen/Qwen2.5-0.5B  | 1g.6gb  | Y | Not PCIe contention (Max bound is not hit)|
| EleutherAI/pythia-160m  | 1g.6gb  | Y | Not PCIe (Max bound is not hit) and only if param offload is enabled  |
| Qwen/Qwen2.5-3B | 1g.6gb | Y | |
# Heterogeneous Training Targeted Workload:
| Workload 1 | MiG Config | Contention Y/N | Note |
| ------------- | ------------- | ------------- | ------------- |
| EleutherAI/pythia-1b  | 1g.6gb  | Y |
| Qwen/Qwen2.5-0.5B  | 1g.6gb  | Y | Not PCIe contention (Max bound is not hit)|
| EleutherAI/pythia-160m  | 1g.6gb  | Y | Not PCIe (Max bound is not hit) and only if param offload is enabled  |

# GPU Conf:
- 1g.6gb
# Benchmarking Cases:
- Case 1: No sharing, each job is assigned to 1g.6gb
- Case 2: Rounds of combinations

# Collected Metrics:
exi