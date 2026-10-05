#!/usr/bin/env python3
import json
import os

home_dir = os.environ.get('HOME', '')
user = os.environ.get('USER', '')
server_id = os.environ.get('SERVER_ID', 'localhost')
client_id = os.environ.get('CLIENT_ID', 'localhost')
server_python = os.environ.get('SERVER_PYTHON', '/usr/bin/python3')
client_python = os.environ.get('CLIENT_PYTHON', '/usr/bin/python3')
local_python = os.environ.get('LOCAL_PYTHON', '/usr/bin/python3')

inventory = {
    "server": {
        "hosts": [server_id],
        "vars" : {
            "ansible_python_interpreter": local_python
        }
    },
    "client": {
        "hosts": [client_id],
        "vars": {
            "ansible_user": user,
            "ansible_connection": "ssh",
            "ansible_ssh_extra_args": f"-F {home_dir}/.ssh/config",
            "ansible_control_path": f"{home_dir}/.ssh/ansible-%%r@%%h:%%p",
            "ansible_python_interpreter": client_python
        }
    },
    "_meta": {
        "hostvars": {
            server_id: {
                "ansible_python_interpreter": server_python
            }
        }
    }
}

print(json.dumps(inventory))