#!/usr/bin/env python
"""
Copyright 2022 Vadim Khitrin <me@vkhitrin.com>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import ansible_runner
import re
import ruamel.yaml
import tempfile

from jiav.api.backends import BaseBackend
from jiav.api.schemas.ansible import schema
from jiav import logger
from collections import namedtuple

# TODO(vkhitirn): Enhance backend to support additional feature such as
#                 inventory

MOCK_STEP = {"playbook": [{"hosts": "localhost", "tasks": [{"shell": "whoami"}]}]}

# Subscribe to logger
jiav_logger = logger.subscribe_to_logger()


def handle_ansi_chars(string):
    """
    Handles ANSI characters

    Returns a string with omitted ANSI characters
    """
    ansi_escape = re.compile(
        r"""
        \x1B    # ESC
        [@-_]   # 7-bit C1 Fe
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    """,
        re.VERBOSE,
    )
    return ansi_escape.sub("", string)


def fix_ansi_list(string_list_to_fix):
    """
    Fixes list of characters containing ANSI characters

    Arguments:
        string_list_to_fix: A list of strings

    Returns a list of strings with applied fixes
    """
    return list(map(handle_ansi_chars, string_list_to_fix))


class AnsibleBackend(BaseBackend):
    """
    Ansible backend object

    Executes Ansible playbook

    Attributes:
        name - Backend name

        schema - json_schema to be used to verify that the supplied setp
        is valid according to the backends's requirments

        step - Ansible playbook
    """

    def __init__(self):
        self.name = "ansible"
        self.schema = schema
        self.step = MOCK_STEP
        super().__init__(self.name, self.schema, self.step)

    def execute_backend(self):
        """
        Execute Ansible playbook

        Returns a namedtuple describing the jiav spec execution
        """
        # Init variables
        playbook_file_ready = bool(False)
        output = list()
        errors = list()
        successful = bool(False)
        # Prepare Ansible kwargs
        ans_kwargs = {}
        # Create a namedtuple to hold the execution result output and errors
        result = namedtuple("result", ["successful", "output", "errors"])
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix=".yml", mode="w+t")
        temp_file_path = temp_file.name
        jiav_logger.debug("Created temp file '{}'".format(temp_file_path))
        # Parse step dict from playbook dict
        step_yaml = self.step["playbook"]
        # Initialize YAML parsing
        yaml = ruamel.yaml.YAML()
        # Iterate over multiple possible plays in playbook
        for play in step_yaml:
            try:
                # Write play to temp file
                yaml.dump([play], temp_file)
                jiav_logger.debug("Written content to temp file")
                playbook_file_ready = True
                # Commit changes to file
                temp_file.seek(0)
            except Exception as e:
                playbook_file_ready = False
                jiav_logger.error(f"Failed to write '{temp_file}' to temp file: '{e}'")
                break
        if playbook_file_ready:
            # Populate kwargs
            # ans_kwargs["private_data_dir"] = "/tmp"
            # jiav_logger.debug(
            # "Set private_data_dir to '{}'".format(ans_kwargs["private_data_dir"])
            # )
            ans_kwargs["playbook"] = temp_file_path
            jiav_logger.debug(f"Set playbook path to '{temp_file_path}'")
            ans_kwargs["verbosity"] = 3
            jiav_logger.debug(f"Set verbosity level to '{ans_kwargs['verbosity']}'")

            # Execute playbook
            playbook_run = ansible_runner.run(**ans_kwargs)
            if playbook_run.stats["failures"]:
                jiav_logger.error("Failed to execute playbook")
                jiav_logger.error("Errors: {}".format(playbook_run.stats["failures"]))
                # TODO(vkhitrin): find a way to better parse errors instead of
                #                 showing the whole play
                errors = fix_ansi_list(playbook_run.stdout.readlines())
            else:
                jiav_logger.debug("Playbook executed successfully")
                successful = True
                playbook_run.stats["failures"] = ""

            # Close and delete temporary file
            temp_file.close()
            # Fix stdout from Ansible playbook execution
            output = fix_ansi_list(playbook_run.stdout.readlines())
            self.result = result(successful, output, errors)
