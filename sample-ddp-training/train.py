import torch
import torch.distributed as dist
import torch.nn as nn
import torch.optim as optim
import os
from torch.nn.parallel import DistributedDataParallel as DDP

class ToyModel(nn.Module):
    def __init__(self):
        super(ToyModel, self).__init__()
        self.net1 = nn.Linear(10, 10)
        self.relu = nn.ReLU()
        self.net2 = nn.Linear(10, 5)

    def forward(self, x):
        return self.net2(self.relu(self.net1(x)))


def demo_basic():
    torch.cuda.set_device(int(os.environ["LOCAL_RANK"]))
    dist.init_process_group("nccl")
    rank = dist.get_rank()

    WORLD_SIZE = int(os.environ['WORLD_SIZE'])
    print(f"Start running basic DDP example on global rank {rank} in {WORLD_SIZE}.")

    # create model and move it to GPU with id rank
    device_id = rank % torch.cuda.device_count()
    model = ToyModel().to(device_id)
    ddp_model = DDP(model, device_ids=[device_id])
    loss_fn = nn.MSELoss()
    optimizer = optim.SGD(ddp_model.parameters(), lr=0.001)

    for i in range(20):
        print(f"step-{i} on global rank {rank} in {WORLD_SIZE}")
        optimizer.zero_grad()
        outputs = ddp_model(torch.randn(20, 10))
        labels = torch.randn(20, 5).to(device_id)
        loss_fn(outputs, labels).backward()
        optimizer.step()
    
    dist.destroy_process_group()


    # Inject runtime Error if necessary
    # raise Exception("Runtime error in code: division by Zero")

    print(f"Finished running basic DDP example on global rank {rank} in {WORLD_SIZE}.")

if __name__ == "__main__":
    demo_basic()