import asyncio

from core.recording.name_inference import infer_names, parse_name_inference


def test_parse_valid_json():
    raw = '[{"speaker":"相手1","name":"田中","confidence":0.82,"evidence":"e"}]'
    out = parse_name_inference(raw)
    assert out[0].speaker == "相手1" and out[0].name == "田中" and out[0].confidence == 0.82


def test_parse_extracts_array_from_surrounding_text():
    raw = 'はい、結果です: [{"speaker":"相手1","name":"佐藤","confidence":0.9,"evidence":"e"}] 以上'
    assert parse_name_inference(raw)[0].name == "佐藤"


def test_parse_garbage_returns_empty():
    assert parse_name_inference("これは説明文です") == []
    assert parse_name_inference("") == []


def test_infer_names_filters_by_threshold_and_excludes_you():
    class _LLM:
        async def generate(self, *, model, prompt, options=None):
            return ('[{"speaker":"相手1","name":"田中","confidence":0.82,"evidence":"e"},'
                    '{"speaker":"相手2","name":"佐藤","confidence":0.40,"evidence":"e"},'
                    '{"speaker":"あなた","name":"X","confidence":0.99,"evidence":"e"}]')
    segs = [{"speaker": "あなた", "text": "田中さんお願いします"},
            {"speaker": "相手1", "text": "はい承知しました"}]
    out = asyncio.run(infer_names(segs, _LLM(), "qwen2.5:14b", threshold=0.65))
    assert out == {"相手1": "田中"}  # 0.40 excluded, あなた excluded
