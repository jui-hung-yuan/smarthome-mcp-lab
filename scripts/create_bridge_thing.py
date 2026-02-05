"""Create AWS IoT Thing for the Smart Home Bridge.

Run once to provision IoT resources:
    uv run python scripts/create_bridge_thing.py

This script:
1. Creates an IoT Thing named 'smarthome-bridge-{bridge_id}'
2. Generates certificates (certificate.pem, private.key)
3. Downloads Amazon Root CA
4. Creates and attaches an IoT policy allowing multi-device control
5. Saves configuration to ~/.smarthome/iot/config.json

The bridge Thing can manage multiple devices. Topic structure:
    Commands:  smarthome/{device_id}/commands/{action}
    Responses: smarthome/{device_id}/responses/{request_id}

Shadow structure:
    {
      "state": {
        "reported": {
          "bridge_connected": true,
          "devices": {
            "device-1": { "is_on": true, ... },
            "device-2": { "is_on": false, ... }
          }
        }
      }
    }
"""

import argparse
import json
import os
import stat
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

DEFAULT_BRIDGE_ID = "home"
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")
ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"


def get_iot_client():
    """Create IoT client using the 'self' AWS profile."""
    session = boto3.Session(profile_name="self", region_name=REGION)
    return session.client("iot")


def create_thing(client, thing_name: str) -> dict:
    """Create IoT Thing if it doesn't exist."""
    try:
        response = client.describe_thing(thingName=thing_name)
        print(f"Thing '{thing_name}' already exists.")
        return response
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            response = client.create_thing(thingName=thing_name)
            print(f"Created Thing: {thing_name}")
            return response
        raise


def create_keys_and_certificate(client) -> dict:
    """Create new certificate and keys."""
    response = client.create_keys_and_certificate(setAsActive=True)
    print(f"Created certificate: {response['certificateId'][:8]}...")
    return response


def create_policy(client, policy_name: str, thing_name: str) -> str:
    """Create IoT policy with permissions for multi-device bridge.

    Allows the bridge to:
    - Connect as the bridge Thing
    - Publish/Subscribe to any device topic under smarthome/
    - Manage the bridge's device shadow
    """
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "iot:Connect",
                "Resource": f"arn:aws:iot:{REGION}:*:client/{thing_name}",
            },
            {
                "Effect": "Allow",
                "Action": ["iot:Publish"],
                "Resource": [
                    # Allow publishing responses for any device
                    f"arn:aws:iot:{REGION}:*:topic/smarthome/*/responses/*",
                    # Allow publishing to bridge's shadow
                    f"arn:aws:iot:{REGION}:*:topic/$aws/things/{thing_name}/shadow/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["iot:Subscribe"],
                "Resource": [
                    # Allow subscribing to commands for any device
                    f"arn:aws:iot:{REGION}:*:topicfilter/smarthome/*/commands/*",
                    # Allow subscribing to bridge's shadow
                    f"arn:aws:iot:{REGION}:*:topicfilter/$aws/things/{thing_name}/shadow/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["iot:Receive"],
                "Resource": [
                    # Allow receiving commands for any device
                    f"arn:aws:iot:{REGION}:*:topic/smarthome/*/commands/*",
                    # Allow receiving shadow updates
                    f"arn:aws:iot:{REGION}:*:topic/$aws/things/{thing_name}/shadow/*",
                ],
            },
        ],
    }

    try:
        client.create_policy(
            policyName=policy_name,
            policyDocument=json.dumps(policy_document),
        )
        print(f"Created policy: {policy_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            print(f"Policy '{policy_name}' already exists.")
            # Update the policy with a new version
            try:
                client.create_policy_version(
                    policyName=policy_name,
                    policyDocument=json.dumps(policy_document),
                    setAsDefault=True,
                )
                print(f"Updated policy: {policy_name}")
            except ClientError:
                pass  # Policy version limit reached, that's fine
        else:
            raise

    return policy_name


def attach_policy_and_thing(
    client, policy_name: str, certificate_arn: str, thing_name: str
) -> None:
    """Attach policy and thing to certificate."""
    try:
        client.attach_policy(policyName=policy_name, target=certificate_arn)
        print("Attached policy to certificate.")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise

    try:
        client.attach_thing_principal(thingName=thing_name, principal=certificate_arn)
        print("Attached certificate to thing.")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise


def download_root_ca(dest_path: Path) -> None:
    """Download Amazon Root CA certificate."""
    if dest_path.exists():
        print(f"Root CA already exists at {dest_path}")
        return

    print(f"Downloading Root CA from {ROOT_CA_URL}...")
    urllib.request.urlretrieve(ROOT_CA_URL, dest_path)
    print(f"Root CA saved to {dest_path}")


def save_certificates(
    cert_dir: Path,
    certificate_pem: str,
    private_key: str,
) -> tuple[Path, Path, Path]:
    """Save certificates to disk with proper permissions."""
    cert_dir.mkdir(parents=True, exist_ok=True)

    cert_path = cert_dir / "certificate.pem"
    key_path = cert_dir / "private.key"
    ca_path = cert_dir / "AmazonRootCA1.pem"

    # Save certificate
    cert_path.write_text(certificate_pem)
    print(f"Certificate saved to {cert_path}")

    # Save private key with restricted permissions
    key_path.write_text(private_key)
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    print(f"Private key saved to {key_path} (chmod 600)")

    # Download root CA
    download_root_ca(ca_path)

    return cert_path, key_path, ca_path


def save_config(
    config_dir: Path,
    endpoint: str,
    thing_name: str,
    cert_path: Path,
    key_path: Path,
    ca_path: Path,
    default_device_id: str,
) -> Path:
    """Save IoT configuration to JSON file."""
    config_path = config_dir / "config.json"

    config = {
        "endpoint": endpoint,
        "thing_name": thing_name,
        # device_id is the default device to register (for single-device mode)
        # The bridge can manage multiple devices
        "device_id": default_device_id,
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "root_ca_path": str(ca_path),
    }

    config_path.write_text(json.dumps(config, indent=2))
    print(f"Configuration saved to {config_path}")

    return config_path


def main():
    parser = argparse.ArgumentParser(
        description="Create AWS IoT Thing for Smart Home Bridge (multi-device)"
    )
    parser.add_argument(
        "--bridge-id",
        default=DEFAULT_BRIDGE_ID,
        help=f"Bridge ID suffix (default: {DEFAULT_BRIDGE_ID})",
    )
    parser.add_argument(
        "--default-device",
        default="tapo-bulb-default",
        help="Default device ID to register (default: tapo-bulb-default)",
    )
    parser.add_argument(
        "--output-dir",
        default="~/.smarthome/iot",
        help="Directory for certificates and config (default: ~/.smarthome/iot)",
    )
    args = parser.parse_args()

    bridge_id = args.bridge_id
    thing_name = f"smarthome-bridge-{bridge_id}"
    policy_name = f"smarthome-bridge-{bridge_id}-policy"

    output_dir = Path(args.output_dir).expanduser()
    cert_dir = output_dir

    print(f"Provisioning IoT Bridge: {thing_name}")
    print(f"Default device: {args.default_device}")
    print(f"Output directory: {output_dir}")
    print()

    client = get_iot_client()

    # Get IoT endpoint
    endpoint_response = client.describe_endpoint(endpointType="iot:Data-ATS")
    endpoint = endpoint_response["endpointAddress"]
    print(f"IoT Endpoint: {endpoint}")
    print()

    # Create Thing
    create_thing(client, thing_name)

    # Check if certificates already exist
    cert_path = cert_dir / "certificate.pem"
    if cert_path.exists():
        print(f"\nCertificates already exist in {cert_dir}")
        print("To regenerate, delete the directory and run again.")

        # Still save/update config
        config_path = save_config(
            output_dir,
            endpoint,
            thing_name,
            cert_dir / "certificate.pem",
            cert_dir / "private.key",
            cert_dir / "AmazonRootCA1.pem",
            args.default_device,
        )
        print(f"\nConfiguration updated: {config_path}")
        return

    # Create certificates
    cert_response = create_keys_and_certificate(client)
    certificate_arn = cert_response["certificateArn"]
    certificate_pem = cert_response["certificatePem"]
    private_key = cert_response["keyPair"]["PrivateKey"]

    # Create policy
    create_policy(client, policy_name, thing_name)

    # Attach policy and thing to certificate
    attach_policy_and_thing(client, policy_name, certificate_arn, thing_name)

    # Save certificates
    cert_path, key_path, ca_path = save_certificates(
        cert_dir, certificate_pem, private_key
    )

    # Save configuration
    config_path = save_config(
        output_dir, endpoint, thing_name, cert_path, key_path, ca_path, args.default_device
    )

    print()
    print("=" * 60)
    print("IoT Bridge provisioned successfully!")
    print()
    print(f"Thing name: {thing_name}")
    print(f"Default device: {args.default_device}")
    print()
    print("To start the bridge:")
    print("  uv run python scripts/run_bridge.py")
    print()
    print("To test with a command (requires aws-cli):")
    print(f'  aws iot-data publish \\')
    print(f'    --topic "smarthome/{args.default_device}/commands/turn_on" \\')
    print(f'    --payload \'{{"request_id":"test-1","parameters":{{}}}}\' \\')
    print(f'    --cli-binary-format raw-in-base64-out')
    print()
    print("Shadow will show device states at:")
    print(f"  AWS Console > IoT Core > Things > {thing_name} > Device Shadows")
    print("=" * 60)


if __name__ == "__main__":
    main()