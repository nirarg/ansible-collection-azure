# Copyright (c) 2018 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import subprocess

from ansible.plugins.inventory import BaseInventoryPlugin

DOCUMENTATION = """
    name: azure_arc_ssh
    short_description: Azure Arc inventory plugin using az ssh config for SSH connection
    description:
        - Fetches Azure Arc-connected machines and generates SSH config using az ssh config command.
    options:
        subscription_id:
            description: Azure Subscription ID
            required: false
        resource_group:
            description: Azure Resource Group where Arc machines are located
            required: true
        username:
            description: Username for SSH connection
            required: true
        config_file_path:
            description: Path where the SSH config file should be generated
            required: false
            default: /tmp/azure_arc_ssh_config
        private_key_file:
            description: Path to the SSH private key file
            required: false
            default: ~/.ssh/id_rsa
"""
# *** Consider adding auth:
# client_id:
#     description: Azure Client ID (App ID)
#     required: false
#     env:
#       - name: AZURE_CLIENT_ID
# client_secret:
#     description: Azure Client Secret
#     required: false
#     env:
#       - name: AZURE_CLIENT_SECRET
# tenant_id:
#     description: Azure Tenant ID
#     required: false
#     env:
#       - name: AZURE_TENANT_ID


class InventoryModule(BaseInventoryPlugin):
    NAME = "azure.azcollection.azure_arc"

    def verify_file(self, path):
        """
        Verify that file is usable by this plugin.
        :param path: the path to the inventory config file
        """
        return path.endswith(("azure_arc.yaml", "azure_arc.yml"))

    def parse(self, inventory, loader, path, cache=True):
        """
        Parses the inventory file and populates it.
        :param loader: an ansible.parsing.dataloader.DataLoader object
        :param path: the path to the inventory config file
        """
        super(InventoryModule, self).parse(inventory, loader, path)

        # Load configuration
        config_data = self._read_config_data(path)
        subscription_id = config_data.get("subscription_id")
        resource_group = config_data.get("resource_group")
        username = config_data.get("username")
        config_file_path = config_data.get(
            "config_file_path", "/tmp/azure_arc_ssh_config"
        )
        private_key_file = config_data.get(
            "private_key_file", os.path.expanduser("~/.ssh/id_rsa")
        )

        if not resource_group:
            raise ValueError("Azure Resource Group must be provided.")
        if not username:
            raise ValueError("Username for SSH connection must be provided.")

        # Try to delete config_file_path, in case it already exists
        if os.path.exists(config_file_path):
            os.remove(config_file_path)

        machines = self.get_arc_machines(resource_group, subscription_id)

        for machine in machines:
            # Generate SSH config using az ssh config
            new_host_name = self.generate_ssh_config(
                machine["name"],
                resource_group,
                username,
                private_key_file,
                config_file_path,
                subscription_id,
            )
            self.inventory.add_host(machine["name"])
            # Use the generated SSH hostname saved in the config file
            self.inventory.set_variable(
                machine["name"], "ansible_host", new_host_name
            )
            self.inventory.set_variable(
                machine["name"], "ansible_connection", "ssh"
            )
            # Use the SSH config file path
            self.inventory.set_variable(
                machine["name"], "ansible_ssh_common_args", f"-F {config_file_path}"
            )

    def get_arc_machines(self, resource_group, subscription_id=None):
        """
        Retrieve Azure Arc-connected machines using Azure CLI (az connectedmachine list).
        :param resource_group: Azure Resource Group where Arc machines are located
        :param subscription_id: Azure Subscription ID (optional)
        """
        command = [
            "az",
            "connectedmachine",
            "list",
            "--resource-group",
            resource_group,
            "--output",
            "json",
        ]

        if subscription_id is not None:
            command = command + ["--subscription", subscription_id]

        try:
            result = subprocess.run(command, capture_output=True, check=True, text=True)
            machines = json.loads(result.stdout)
            return [
                {
                    "name": machine["name"],
                }
                for machine in machines
            ]
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to retrieve Azure Arc machines: {e}")

    def generate_ssh_config(
        self,
        vm_name,
        resource_group,
        local_user,
        private_key_file,
        config_file_path,
        subscription_id=None,
    ):
        """
        Generate an SSH config record for the machine using Azure CLI (az ssh config).
        Generate an SSH config file if doesn't already exist.
        :param vm_name: The name of the VM
        :param resource_group: Azure Resource Group where Arc machines are located
        :param local_user: The username for a local user in the VM
        :param private_key_file: The RSA private key file path used to ssh the VM with local_user
        :param config_file_path: The file path to write the SSH config to
        :param subscription_id: Azure Subscription ID (optional)
        """
        command = [
            "az",
            "ssh",
            "config",
            "--vm-name",
            vm_name,
            "--resource-group",
            resource_group,
            "--local-user",
            local_user,
            "--private-key-file",
            private_key_file,
            "--file",
            config_file_path,
        ]

        if subscription_id is not None:
            command = command + ["--subscription", subscription_id]

        try:
            subprocess.run(command, check=True)
            return resource_group + "-" + vm_name + "-" + local_user
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to generate SSH config: {e}")
