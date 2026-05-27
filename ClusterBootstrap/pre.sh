#!/bin/bash

######################
# Containerd Setup
# We Assume Containerd is already installed
######################

# Create config.toml file
echo "Generating containerd config.toml file..."
mkdir -p /tmp/containerd
containerd config default > /tmp/containerd/config.toml

# Configure systemd cgroup driver
echo "Configuring systemd cgroup driver for containerd..."
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /tmp/containerd/config.toml

# Move the config.toml file to /etc/containerd
echo "Moving config.toml to /etc/containerd..."
sudo mv /tmp/containerd/config.toml /etc/containerd/config.toml
rm -rf /tmp/containerd

# Restart containerd to apply changes
echo "Restarting containerd to apply changes..."
sudo systemctl restart containerd


