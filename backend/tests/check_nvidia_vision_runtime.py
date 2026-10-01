"""NVIDIA vision contract and failure checks; no network, database, or credentials."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import fitz
from pydantic import ValidationError

from northstar_api.config import Settings
from northstar_api.services import hybrid_extraction as hybrid
from northstar_api.services import vision


async def main() -> None:
    settings = Settings(_env_file=None, nvidia_api_key="test-only-key")
    assert settings.extraction_vision_max_tokens == 512
    for overrides in (
        {"extraction_vision_provider": "ollama"},
        {"extraction_vision_model": "another-model"},
    ):
        try:
            Settings(_env_file=None, **overrides)
        except ValidationError:
            pass
        else:
            raise AssertionError("An alternative vision provider/model was accepted")

    response = SimpleNamespace(
        content="Value -12.50",
        response_metadata={"finish_reason": "stop"},
        additional_kwargs={"reasoning_content": "Not source text"},
    )
    client = Mock(ainvoke=AsyncMock(return_value=response), invoke=Mock(return_value=response))
    with patch.object(vision, "ChatNVIDIA", return_value=client) as constructor:
        assert await hybrid._read_image(b"image-bytes", settings) == "Value -12.50"
        constructor.assert_called_once_with(
            model="meta/llama-3.2-11b-vision-instruct",
            api_key="test-only-key",
            temperature=1,
            top_p=1,
            max_completion_tokens=512,
            timeout=120,
        )
        messages = client.ainvoke.call_args.args[0]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"][0]["image_url"]["url"] == "data:image/png;base64,aW1hZ2UtYnl0ZXM="
        assert "Value -12.50" not in str(messages)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "page.png"
            image_path.write_bytes(b"image-bytes")
            with patch.object(vision, "get_settings", return_value=settings):
                assert vision.extract_vision_text(str(image_path)) == "Value -12.50"
            assert client.invoke.call_args.args[0] == messages

        for reason in ("length", "max_tokens", "content_filter", None):
            response.response_metadata = {"finish_reason": reason}
            try:
                await hybrid._read_image(b"image", settings)
            except ValueError:
                pass
            else:
                raise AssertionError(f"An incomplete response was accepted: {reason}")

        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "Value -12.50")
            package = await hybrid.extract_document(document.tobytes(), "fixture.pdf", settings)
        assert package.record["pages"][0]["selected_text"] is None
        assert package.issues[0]["code"] == "VISION_CAPABILITY_FAILED"
        assert "Verified release: BLOCKED" in package.validation_text()

        response.response_metadata = {"finish_reason": "stop"}
        for content in ("", "  ", []):
            response.content = content
            try:
                await hybrid._read_image(b"image", settings)
            except ValueError:
                pass
            else:
                raise AssertionError("An empty response was accepted")

    with patch.object(vision, "ChatNVIDIA") as constructor:
        try:
            await hybrid._read_image(b"image", Settings(_env_file=None, nvidia_api_key=None))
        except ValueError:
            pass
        else:
            raise AssertionError("Missing credentials were accepted")
        constructor.assert_not_called()
    print("NVIDIA vision contract and failure checks passed")


if __name__ == "__main__":
    asyncio.run(main())
