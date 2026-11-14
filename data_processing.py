from pathlib import Path
import requests
from tqdm import tqdm

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

FILES = {
    "gale_dem_1m.tif":
        "https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars/MSL/MSL_Gale_DEM_Mosaic_1m_v3.tif",

    "gale_colour_mosaic_cog.tif":
        "https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars/MSL/MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif",
}


def download_with_resume(
        url: str,
        destination: Path,
        chunk_size: int = 8 * 1024 * 1024
):

    existing_bytes = (
        destination.stat().st_size
        if destination.exists()
        else 0
    )

    try:
        head = requests.head(
            url,
            allow_redirects=True,
            timeout=30
        )

        remote_size = int(
            head.headers.get(
                "Content-Length",
                0
            )
        )

    except Exception as e:
        print(f"Metadata error: {e}")
        return

    print(f"\nDownloading {destination.name}")
    print(f"Remote size: {remote_size:,}")
    print(f"Local size : {existing_bytes:,}")

    if (
        remote_size > 0 and
        existing_bytes >= remote_size
    ):
        print("Already downloaded.")
        return

    headers = {}
    mode = "wb"

    if existing_bytes > 0:
        headers["Range"] = (
            f"bytes={existing_bytes}-"
        )
        mode = "ab"

    try:

        with requests.get(
            url,
            headers=headers,
            stream=True,
            timeout=(30, 300),
            allow_redirects=True,
        ) as response:

            if response.status_code == 416:
                print("File already complete.")
                return

            response.raise_for_status()

            remaining = int(
                response.headers.get(
                    "Content-Length",
                    0
                )
            )

            total = (
                existing_bytes +
                remaining
            )

            with open(
                destination,
                mode
            ) as output, tqdm(
                total=total,
                initial=existing_bytes,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=destination.name,
            ) as progress:

                for chunk in response.iter_content(
                    chunk_size=chunk_size
                ):
                    if chunk:
                        output.write(chunk)
                        progress.update(
                            len(chunk)
                        )

        print(f"Saved: {destination}")

    except Exception as e:
        print(f"Download failed:\n{e}")


def main():

    for filename, url in FILES.items():

        destination = (
            RAW_DIR /
            filename
        )

        download_with_resume(
            url,
            destination
        )


if __name__ == "__main__":
    main()