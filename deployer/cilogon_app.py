"""
### Summary

This is a helper script that can create/update/get/delete CILogon clients
using the 2i2c administrative client provided by CILogon.
More details here: https://cilogon.github.io/oa4mp/server/manuals/dynamic-client-registration.html

### Use cases

The script can be used to:

- `create` a CILogon OAuth application for a hub and store the credentials safely
- `update` the callback urls of an existing hub CILogon client
- `delete` a CILogon OAuth application when a hub is removed or changes auth methods
- `get` details about an existing hub CILogon client
- `get-all` existing 2i2c CILogon OAuth applications

### Running the script

Get usage instructions about each of the available subcommands (create/update/get/get-all/delete)
by executing the script with `--help` flag, from the root of the repository:

- python deployer/cilogon_app.py create --help
"""

import argparse
import base64
import subprocess
from pathlib import Path

import requests
from file_acquisition import find_absolute_path_to_cluster_file, get_decrypted_file
from ruamel.yaml import YAML
from yarl import URL

yaml = YAML(typ="safe")


class CILogonAdmin:
    timeout = 5.0

    def __init__(self, admin_id, admin_secret):
        self.admin_id = admin_id
        self.admin_secret = admin_secret

        token_string = f"{self.admin_id}:{self.admin_secret}"
        bearer_token = base64.urlsafe_b64encode(token_string.encode("utf-8")).decode(
            "ascii"
        )

        self.base_headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _url(self, id=None):
        url = "https://cilogon.org/oauth2/oidc-cm"

        if id is None:
            return url

        return str(URL(url).with_query({"client_id": id}))

    def create(self, body):
        """Creates a new client

        Args:
           body (dict): Attributes for the new client

        Returns a dict containing the client details.

        See: https://github.com/ncsa/OA4MP/blob/HEAD/oa4mp-server-admin-oauth2/src/main/scripts/oidc-cm-scripts/cm-post.sh
        """

        headers = self.base_headers.copy()
        response = requests.post(
            self._url(), json=body, headers=headers, timeout=self.timeout
        )

        client_name = body["client_name"]

        if response.status_code != 200:
            print(
                f"An error occured when creating the {client_name} client. \n Error was {response.text}."
            )
            response.raise_for_status()

        print(f"Successfully created a new CILogon client for {client_name}!")
        return response.json()

    def get(self, id=None):
        """Retrieves a client by its id.

        Args:
           id (str): Id of the client to get

        Returns a dict containing the client details.

        See: https://github.com/ncsa/OA4MP/blob/HEAD/oa4mp-server-admin-oauth2/src/main/scripts/oidc-cm-scripts/cm-get.sh
        """

        headers = self.base_headers.copy()
        response = requests.get(
            self._url(id), params=None, headers=headers, timeout=self.timeout
        )

        if response.status_code != 200:
            print(
                f"An error occured when getting the details of {id} client. \n Error was {response.text}."
            )
            response.raise_for_status()

        print(f"Successfully got the details for {id} client!")
        return response.json()

    def update(self, id, body):
        """Modifies a client by its id.

        The client_secret attribute cannot be updated.
        Note that any values missing will be deleted from the information for the server!
        Args:
           id (str): Id of the client to modify
           body (dict): Attributes to modify.

        Returns 200 OK or raises an error if the update request returned anything other than 200..

        See: https://github.com/ncsa/OA4MP/blob/HEAD/oa4mp-server-admin-oauth2/src/main/scripts/oidc-cm-scripts/cm-put.sh
        """
        headers = self.base_headers.copy()
        response = requests.put(
            self._url(id), json=body, headers=headers, timeout=self.timeout
        )

        client_name = body["client_name"]

        if response.status_code != 200:
            print(
                f"An error occured when updating the {client_name} client. \n Error was {response.text}."
            )
            response.raise_for_status()

        print("Client updated succesfuly!")
        return response.status_code

    def delete(self, id):
        """Deletes the client associated with the id.

        Args:
           id (str): Id of the client to delete

        Returns 200 OK or raises an error if the delete request returned anything other than 200.

        See: https://github.com/ncsa/OA4MP/blob/HEAD/oa4mp-server-admin-oauth2/src/main/scripts/oidc-cm-scripts/cm-delete.sh
        """

        headers = self.base_headers.copy()
        response = requests.delete(self._url(id), headers=headers, timeout=self.timeout)

        if response.status_code != 200:
            print(
                f"An error occured when deleting the {id} client. \n Error was {response.text}."
            )
            response.raise_for_status()

        print(f"Successfully deleted the {id} client!")
        return response.status_code


class CILogonClientProvider:
    def __init__(self, admin_id, admin_secret):
        self.admin_id = admin_id
        self.admin_secret = admin_secret

    @property
    def admin_client(self):
        """
        Return a CILogonAdmin instance
        """
        if not hasattr(self, "_cilogon_admin"):
            self._cilogon_admin = CILogonAdmin(self.admin_id, self.admin_secret)

        return self._cilogon_admin

    def _build_client_details(self, cluster_name, hub_name, callback_url):
        client_details = {
            "client_name": f"{cluster_name}-{hub_name}",
            "app_type": "web",
            "redirect_uris": [callback_url],
            "scope": "openid email org.cilogon.userinfo",
        }

        return client_details

    def _build_config_filename(self, cluster_name, hub_name):
        cluster_config_dir_path = find_absolute_path_to_cluster_file(
            cluster_name
        ).parent

        return cluster_config_dir_path.joinpath(f"enc-{hub_name}.secret.values.yaml")

    def _persist_client_credentials(self, client, hub_type, config_filename):
        auth_config = {}
        jupyterhub_config = {
            "jupyterhub": {
                "hub": {
                    "config": {
                        "CILogonOAuthenticator": {
                            "client_id": client["client_id"],
                            "client_secret": client["client_secret"],
                        }
                    }
                }
            }
        }

        if hub_type != "basehub":
            auth_config["basehub"] = jupyterhub_config
        else:
            auth_config = jupyterhub_config

        with open(config_filename, "w+") as f:
            yaml.dump(auth_config, f)
        subprocess.check_call(["sops", "--encrypt", "--in-place", config_filename])

    def _load_client_id(self, config_filename):
        try:
            with get_decrypted_file(config_filename) as decrypted_path:
                with open(decrypted_path) as f:
                    auth_config = yaml.load(f)

            basehub = auth_config.get("basehub", None)
            if basehub:
                return auth_config["basehub"]["jupyterhub"]["hub"]["config"][
                    "CILogonOAuthenticator"
                ]["client_id"]
            return auth_config["jupyterhub"]["hub"]["config"]["CILogonOAuthenticator"][
                "client_id"
            ]
        except FileNotFoundError:
            print(
                "Oops! The CILogon client you requested to doesn't exist! Please create it first."
            )
            return

    def create_client(self, cluster_name, hub_name, hub_type, callback_url):
        client_details = self._build_client_details(
            cluster_name, hub_name, callback_url
        )
        config_filename = self._build_config_filename(cluster_name, hub_name)

        if Path(config_filename).is_file():
            print(
                f"""
                Oops! A CILogon client already exists for this hub!
                Use the update subcommand to update it or delete {config_filename} if you want to generate a new one.
                """
            )
            return

        # Ask CILogon to create the client
        print(f"Creating client with details {client_details}...")
        client = self.admin_client.create(client_details)

        # Persist and encrypt the client credentials
        self._persist_client_credentials(client, hub_type, config_filename)
        print(f"Client credentials encrypted and stored to {config_filename}.")

    def update_client(self, cluster_name, hub_name, callback_url):
        client_details = self._build_client_details(
            cluster_name, hub_name, callback_url
        )
        config_filename = self._build_config_filename(cluster_name, hub_name)

        client_id = self._load_client_id(config_filename)

        # No client has been found for this hub
        if not client_id:
            return

        print(f"Updating the existing CILogon client for {cluster_name}-{hub_name}...")
        return self.admin_client.update(client_id, client_details)

    def get_client(self, cluster_name, hub_name):
        config_filename = self._build_config_filename(cluster_name, hub_name)

        client_id = self._load_client_id(config_filename)

        # No client has been found
        if not client_id:
            return

        print(
            f"Getting the stored CILogon client details for {cluster_name}-{hub_name}..."
        )
        print(self.admin_client.get(client_id))

    def delete_client(self, cluster_name, hub_name, client_id=None):
        if not client_id:
            if not cluster_name or not hub_name:
                print(
                    "Please provide either the client id to delete or the cluster and hub name."
                )
                return

            config_filename = self._build_config_filename(cluster_name, hub_name)
            client_id = self._load_client_id(config_filename)

            # No client has been found
            if not client_id:
                return

        print(f"Deleting the CILogon client details for {client_id}...")
        print(self.admin_client.delete(client_id))

    def get_all_clients(self):
        print("Getting all existing OAauth client applications...")
        clients = self.admin_client.get()
        for c in clients["clients"]:
            print(c)


def main():
    argparser = argparse.ArgumentParser(
        description="""A command line tool to create/update/delete
        CILogon clients.
        """
    )
    subparsers = argparser.add_subparsers(
        required=True, dest="action", help="Available subcommands"
    )

    # Create subcommand
    create_parser = subparsers.add_parser(
        "create",
        help="Create a CILogon client",
    )

    create_parser.add_argument(
        "cluster_name",
        type=str,
        help="The name of the cluster where the hub lives",
    )

    create_parser.add_argument(
        "hub_name",
        type=str,
        help="The hub for which we'll create a CILogon client",
    )

    create_parser.add_argument(
        "hub_type",
        type=str,
        help="The type of hub for which we'll create a CILogon client.",
        default="basehub",
    )

    create_parser.add_argument(
        "callback_url",
        type=str,
        help="URL that is invoked after OAuth authorization",
    )

    # Update subcommand
    update_parser = subparsers.add_parser(
        "update",
        help="Update a CILogon client",
    )

    update_parser.add_argument(
        "cluster_name",
        type=str,
        help="The name of the cluster where the hub lives",
    )

    update_parser.add_argument(
        "hub_name",
        type=str,
        help="The hub for which we'll update the CILogon client",
    )

    update_parser.add_argument(
        "callback_url",
        type=str,
        help="""
        New callback_url to associate with the client.
        This URL is invoked after OAuth authorization
        """,
    )

    # Get subcommand
    get_parser = subparsers.add_parser(
        "get",
        help="Retrieve details about an existing CILogon client",
    )

    get_parser.add_argument(
        "cluster_name",
        type=str,
        help="The name of the cluster where the hub lives",
    )

    get_parser.add_argument(
        "hub_name",
        type=str,
        help="The hub for which we'll retrieve the CILogon client details",
    )

    # Get all subcommand
    subparsers.add_parser(
        "get-all",
        help="Retrieve details about an existing CILogon client",
    )

    # Delete subcommand
    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete an existing CILogon client",
    )

    delete_parser.add_argument(
        "cluster_name",
        type=str,
        help="The name of the cluster where the hub lives or none if --id is present",
        default="",
        nargs="?",
    )

    delete_parser.add_argument(
        "hub_name",
        type=str,
        help="The hub for which we'll delete the CILogon client details or none if --id is present",
        default="",
        nargs="?",
    )

    delete_parser.add_argument(
        "--id",
        type=str,
        help="The id of the client to delete of the form cilogon:/client_id/<id>",
    )

    args = argparser.parse_args()

    # This filepath is relative to the PROJECT ROOT
    general_auth_config = "shared/deployer/enc-auth-providers-credentials.secret.yaml"
    with get_decrypted_file(general_auth_config) as decrypted_file_path:
        with open(decrypted_file_path) as f:
            config = yaml.load(f)

    cilogon = CILogonClientProvider(
        config["cilogon_admin"]["client_id"], config["cilogon_admin"]["client_secret"]
    )

    if args.action == "create":
        cilogon.create_client(
            args.cluster_name,
            args.hub_name,
            args.hub_type,
            args.callback_url,
        )
    elif args.action == "update":
        cilogon.update_client(
            args.cluster_name,
            args.hub_name,
            args.callback_url,
        )
    elif args.action == "get":
        cilogon.get_client(
            args.cluster_name,
            args.hub_name,
        )
    elif args.action == "delete":
        cilogon.delete_client(args.cluster_name, args.hub_name, args.id)
    elif args.action == "get-all":
        cilogon.get_all_clients()


if __name__ == "__main__":
    main()
