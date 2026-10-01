"""Manual NVIDIA image capability check. Requires NVIDIA_API_KEY."""

import asyncio

from northstar_api.config import Settings
from northstar_api.services.vision import verify_image_capability


async def main() -> None:
    result, _ = await verify_image_capability(Settings())
    if result["status"] != "PASSED":
        raise RuntimeError(
            "NVIDIA image-content capability check failed; check credentials, model access and response completion"
        )
    print("NVIDIA model correctly read a random value present only in image pixels")


if __name__ == "__main__":
    asyncio.run(main())
