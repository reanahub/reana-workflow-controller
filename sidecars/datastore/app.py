import os
import re
import sys


def createFolders(aliases, base_dir):
    try:
        for i in range(0, len(aliases)):
            target_path = os.path.join(base_dir, aliases[i][0])
            target_path = os.path.join(target_path, aliases[i][1])
            if not os.path.exists(target_path):
                os.makedirs(target_path)
                print(f"Created folder: {target_path}")
            else:
                print(f"Folder exists: {target_path}")
        return True
    except Exception as e:
        print(f"A error accrued during the creation of the s3-buckets: {e}")
        return False


def getCredentials(aliases):
    aliases_credentials = []
    try:
        for alias in aliases:
            temp_list = [alias]
            temp_list.append(os.getenv(f"S3_TO_LOCAL_{alias}_BUCKET"))
            temp_list.append(os.getenv(f"S3_TO_LOCAL_{alias}_HOST"))
            temp_list.append(os.getenv(f"S3_TO_LOCAL_{alias}_REGION"))
            temp_list.append(os.getenv(f"S3_TO_LOCAL_{alias}_ACCESS_KEY"))
            temp_list.append(os.getenv(f"S3_TO_LOCAL_{alias}_SECRET_KEY"))
            aliases_credentials.append(temp_list)
        return aliases_credentials
    except Exception as e:
        print(f"A error accrued during load of S3 credentials: {e}")
        return False


def createS3Mounts(aliases, base_dir):
    for i in (0, len(aliases) - 2):
        try:
            with open(".passwd-s3fs", mode="w", encoding="utf-8") as f:
                f.write(f"{aliases[i][4]}:{aliases[i][5]}")
            os.system("chmod 600 .passwd-s3fs")
            target_path = os.path.join(base_dir, aliases[i][0])
            target_path = os.path.join(target_path, aliases[i][1])
            cmd = f"s3fs {aliases[i][1]} {target_path} -o passwd_file=.passwd-s3fs -o url={aliases[i][2]} -o endpoint={aliases[i][3]} -o use_path_request_style -o allow_other"
            rc = os.system(cmd)
            if rc != 0:
                print(
                    f"s3fuse returned a non‑zero status ({rc >> 8}) for alias '{aliases[i][0]}'",
                    file=sys.stderr,
                )
            else:
                print(f"Successfully mounted '{aliases[i][0]}'")
                with open("/etc/active_mounts.txt", "a") as f:
                    f.write(f"{target_path}\n")
            os.system("rm .passwd-s3fs")
        except Exception as e:
            print(f"A error accrued during the mounting of alias {aliases[i][0]}: {e}")
            return False


def main():
    base_dir = "/s3-data"

    # Ensure the base directory exists
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
        print(f"Base directory created: {base_dir}")

    # Regex pattern: S3_TO_LOCAL_<ALIAS>_ALIAS
    # The (.*) captures the <ALIAS> part
    pattern = re.compile(r"^S3_TO_LOCAL_(.*)_ALIAS$")

    print("Scanning environment variables for S3 aliases...")

    aliases = []
    for key, value in os.environ.items():
        match = pattern.match(key)
        if match:
            aliases.append(value)

    aliases = getCredentials(aliases)
    createFolders(aliases, base_dir)
    createS3Mounts(aliases, base_dir)

    if len(aliases) == 0:
        print("No environment variables matching 'S3_TO_LOCAL_*_ALIAS' found.")
    else:
        print(f"Processed {len(aliases)} S3 alias(es).")


if __name__ == "__main__":
    main()
