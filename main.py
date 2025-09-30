import asyncio
import platform
import sys
from functools import partial

import inquirer
from colorama import Fore
from inquirer import themes
from rich.console import Console
from rich.table import Table

from check_python import check_python_version
from data.constants import PROJECT_NAME
from functions.activity import activity
from utils.create_files import create_files, reset_folder
from utils.csv_exporter.exporter import export_to_csv
from utils.db_import_export_sync import Export, Import, Sync
from utils.git_version import check_for_updates
from utils.output import show_channel_info

console = Console()

PROJECT_ACTIONS = [
    "1. Run All Activities",
    "2. Start Complete SpriteType Games",
    "3. Start Complete All Portals Games",
    "4. Start Complete Galxe Quests",
    "5. Start Onchain Actions",
    "Back",
]

UTILS_ACTIONS = [
    "1. Reset files Folder",
    "Back",
]


async def choose_action():
    cat_question = [
        inquirer.List(
            "category",
            message=Fore.LIGHTBLACK_EX + "Choose action",
            choices=["DB Actions", PROJECT_NAME, "Utils", "Exit"],
        )
    ]

    answers = inquirer.prompt(cat_question, theme=themes.Default())
    category = answers.get("category")

    if category == "Exit":
        console.print(f"[bold red]Exiting {PROJECT_NAME}...[/bold red]")
        raise SystemExit(0)

    if category == "DB Actions":
        actions = [
            "Import wallets to Database",
            "Sync wallets with tokens and proxies",
            "Export wallets to TXT",
            "Export data from database to CSV",
            "Back",
        ]

    if category == PROJECT_NAME:
        actions = PROJECT_ACTIONS

    if category == "Utils":
        actions = UTILS_ACTIONS

    act_question = [
        inquirer.List(
            "action",
            message=Fore.LIGHTBLACK_EX + f"Choose action in '{category}'",
            choices=actions,
        )
    ]

    act_answer = inquirer.prompt(act_question, theme=themes.Default())
    action = act_answer["action"]

    if action == "Import wallets to Database":
        console.print(f"[bold blue]Starting Import Wallets to DB[/bold blue]")
        await Import.wallets()
    elif action == "Sync wallets with tokens and proxies":
        console.print(f"[bold blue]Starting sync data in DB[/bold blue]")
        await Sync.sync_wallets_with_tokens_and_proxies()
    elif action == "Export wallets to TXT":
        console.print(f"[bold blue]Starting Import Wallets to DB[/bold blue]")
        await Export.wallets_to_txt()
    elif action == "Export data from database to CSV":
        pk = [inquirer.List("pk", message="Export private keys to CSV?", choices=["yes", "no"], default="no")]
        pk_answer = inquirer.prompt(pk, theme=themes.Default())

        if pk_answer["pk"] == "yes":
            func_to_export = partial(export_to_csv, export_private_keys=True)
        elif pk_answer["pk"] == "no":
            func_to_export = partial(export_to_csv, export_private_keys=False)
        else:
            sys.exit("Not supported type for export private keys.")

        table = Table(title="Export type explanation")
        table.add_column("Mode", style="bold cyan")
        table.add_column("Description", style="")

        table.add_row("Overwrite", "Overwrite CSV file if it already exists")
        table.add_row("Suffix", "Add database name as suffix to the CSV file")
        table.add_row("Merge", "Merge all databases into a single CSV with column [source_db]")

        console.print(table)

        export_type = [
            inquirer.List(
                "type",
                message="Choose export type",
                choices=["Overwrite", "Suffix", "Merge"],
            )
        ]
        export_type_answer = inquirer.prompt(export_type, theme=themes.Default())
        mode = export_type_answer["type"].lower()

        if mode in ("overwrite", "suffix", "merge"):
            result = func_to_export(mode=mode)
        else:
            sys.exit("Not supported type for export type.")

        success, export_path = result
        if success:
            console.print("[bold green]Successfully exported to:[/bold green]", export_path)
        else:
            console.print("[bold red]Export Failed[/bold red]")
    elif action == "1. Run All Activities":
        await activity(action=1)

    elif action == "2. Start Complete SpriteType Games":
        await activity(action=2)

    elif action == "3. Start Complete All Portals Games":
        await activity(action=3)

    elif action == "4. Start Complete Galxe Quests":
        await activity(action=4)

    elif action == "5. Start Onchain Actions":
        await activity(action=5)

    elif action == "1. Reset files Folder":
        console.print("This action will delete the files folder and reset it.")
        answer = input("Are you sure you want to perform this action? y/N ")
        if answer.lower() == "y":
            reset_folder()
            console.print("Files folder success reset")

    elif action == "Exit":
        console.print(f"[bold red]Exiting {PROJECT_NAME}...[/bold red]")
        raise SystemExit(0)

    await choose_action()


async def main():
    check_python_version()
    create_files()

    await check_for_updates(repo_name=PROJECT_NAME)
    await choose_action()


if __name__ == "__main__":
    show_channel_info(PROJECT_NAME)

    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
