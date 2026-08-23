import sys
import textwrap

import odoo.release

from .command import (
    DEFAULT_COMMAND,
    PROG_NAME,
    Command,
    commands,
    find_command,
    load_addons_commands,
    load_internal_commands,
)


class Help(Command):
    """Display the list of available commands"""

    template = textwrap.dedent("""\
        usage: {prog_name} [--addons-path=PATH,...] <command> [...]

        Odoo {version}
        Available commands:

        {command_list}

        Use '{prog_name} {default_command} --help' for regular server options.
        Use '{prog_name} <command> --help' for other individual commands options.
    """)

    def run(self, args: list[str]) -> None:
        if args and Command.is_valid_name(args[0]):
            # `odoo-bin help <command>` used to print this list, i.e. answer a
            # question about one command with the index of all of them.
            return self.run_command_help(args[0])

        load_internal_commands()
        load_addons_commands()

        padding = max((len(cmd_name) for cmd_name in commands), default=0) + 2
        name_desc = [
            (
                cmd_name,
                (cmd.__doc__ or cmd.description or "")
                .strip()
                .partition("\n")[0]
                .strip(),
            )
            for cmd_name, cmd in sorted(commands.items())
        ]
        command_list = "\n".join(
            f"    {name:<{padding}}{desc}" for name, desc in name_desc
        )

        print(
            Help.template.format(
                prog_name=PROG_NAME,
                version=odoo.release.version,
                command_list=command_list,
                default_command=DEFAULT_COMMAND,
            )
        )
        return None

    def run_command_help(self, name: str) -> None:
        """Render ``name``'s own ``--help``, the way the user asked for it."""
        command = find_command(name)
        if command is None:
            sys.exit(
                f"Unknown command {name!r}.\n"
                f"Use '{PROG_NAME} help' to see the list of available commands."
            )
        command().run(["--help"])
