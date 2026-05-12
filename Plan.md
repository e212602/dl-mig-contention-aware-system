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







