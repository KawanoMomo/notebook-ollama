from core.ollama.messages import build_image_message


def test_build_image_message_with_images():
    msg = build_image_message(role="user", content="質問です", images_b64=["AAAA", "BBBB"])
    assert msg == {"role": "user", "content": "質問です", "images": ["AAAA", "BBBB"]}


def test_build_image_message_without_images_omits_key():
    msg = build_image_message(role="user", content="質問です", images_b64=[])
    assert msg == {"role": "user", "content": "質問です"}
    assert "images" not in msg
