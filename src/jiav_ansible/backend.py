#!/usr/bin/env python

import shutil
import json
import re
import tempfile
from typing import Any, Dict, List

import ruamel.yaml
from ansible_runner import Runner, RunnerConfig

from jiav import logger
from jiav.backend import BaseBackend, Result

# TODO: Enhance backend to support additional feature such as
#       inventory


# Subscribe to logger
jiav_logger = logger.subscribe_to_logger()


def handle_ansi_chars(string: str) -> str:
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


def fix_ansi_list(string_list_to_fix: List[str]) -> List[str]:
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

    MOCK_STEP = {"playbook": [{"hosts": "localhost", "tasks": [{"shell": "whoami"}]}]}
    SCHEMA = {
        "type": "object",
        "required": [
            "playbook",
        ],
        "properties": {"playbook": {"type": "array"}},
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.name = "ansible"
        self.schema = self.SCHEMA
        self.step = self.MOCK_STEP
        super().__init__(self.name, self.schema, self.step)

    def execute_backend(self) -> None:
        """
        Execute Ansible playbook

        Returns a namedtuple describing the jiav spec execution
        """

        def _event_handler(data: Dict[str, Any]) -> None:
            event = data.get("event")
            event_data = data.get("event_data")
            if event == "runner_on_failed":
                errors.append(
                    "".join(
                        (
                            f"Task '{event_data.get("resolved_action")}' ",
                            f"failed on host '{event_data.get("host")}' ",
                            f"with result: '{event_data.get("res")}'",
                        )
                    )
                )
            elif event == "runner_on_ok":
                output.append(
                    "".join(
                        (
                            f"Task '{event_data.get("resolved_action")}' ",
                            f"succeeded on host '{event_data.get("host")}' ",
                            f"with result: '{event_data.get("res")}'",
                        )
                    )
                )

        def _artifacts_handler(artifacts_dir: str) -> None:
            try:
                shutil.rmtree(artifacts_dir)
            except Exception as e:
                jiav_logger.error(
                    f"Failed to remove artifacts dir '{artifacts_dir}': '{e}'"
                )
            try:
                temp_file.close()
            except Exception as e:
                jiav_logger.error(f"Failed to close temp file '{temp_file}': '{e}'")

        # Init variables
        playbook_file_ready: bool = False
        output: List = list()
        errors: List = list()
        successful: bool = False
        # Prepare Ansible kwargs
        ans_kwargs: Dict[str, Any] = {}
        # Create a namedtuple to hold the execution result output and errors
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix=".yml", mode="w+t")
        temp_private_dir = tempfile.mkdtemp()
        temp_file_path = temp_file.name
        jiav_logger.debug(f"Created temp file '{temp_file_path}'")
        jiav_logger.debug(f"Created temp dir '{temp_private_dir}'")
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
            ans_kwargs["binary"] = (
                "/Users/vadimk/.local/pipx/venvs/jiav/bin/ansible-playbook"
            )
            ans_kwargs["private_data_dir"] = temp_private_dir
            ans_kwargs["cmdline"] = temp_file_path
            jiav_logger.debug(f"Set playbook path to '{temp_file_path}'")
            ans_kwargs["verbosity"] = 3
            jiav_logger.debug(f"Set verbosity level to '{ans_kwargs['verbosity']}'")
            # Prepare ansible runner
            rc: RunnerConfig = RunnerConfig(**ans_kwargs)
            rc.prepare()
            # Execute playbook
            r: Runner = Runner(
                config=rc,
                event_handler=_event_handler,
                artifacts_handler=_artifacts_handler,
            )
            playbook_run: Runner = r.run()
            # Pase the returned tuple
            if playbook_run[0] in ["failed", "timeout"]:
                jiav_logger.error(f"Failed to execute playbook\n{errors}")
            else:
                jiav_logger.info("Playbook executed successfully")
                successful = True
                jiav_logger.debug(f"Playbook output: {output}")

            # Fix stdout from Ansible playbook execution
            # output = fix_ansi_list(playbook_run.stdout.readlines())
            self.result = Result(successful, output, errors)
