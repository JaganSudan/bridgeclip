import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from clip_engine import recover_review
from clip_engine.services.manual_editor import prepare_project
from clip_engine.services.intelligence_planner import ClipPlanSegment
from clip_engine.services.rendering_service import RenderingError
from tests.test_coherence_review import reviewer, transcript


@pytest.mark.parametrize('error', [RenderingError('encoding failed'), asyncio.CancelledError()])
def test_preview_failure_keeps_paid_reviews_and_source(tmp_path, error):
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'source')
    run = tmp_path / 'run'; run.mkdir()
    gate, _ = reviewer(lambda state, question: False)
    renderer = SimpleNamespace(_get_video_dimensions=AsyncMock(return_value=(1920, 1080)),
        capture_framing_source=AsyncMock(side_effect=error))
    request = SimpleNamespace(aspect_ratio='9:16', layout_style='fit', include_captions=False,
        caption_preset='pop', video_speed=1)
    with pytest.raises(type(error)):
        asyncio.run(prepare_project(request, [ClipPlanSegment(0, 5000, 90, summary='Saved')], transcript(),
            SimpleNamespace(video_path=str(source), metadata=SimpleNamespace(title='Video', duration_seconds=12)),
            renderer, gate, str(run), lambda *_: None))
    project = json.loads((run / 'editor-project.json').read_text())
    assert project['candidates'][0]['review']['decision'] == 'needs_attention'
    assert not project.get('frame_preview')
    assert (run / 'editor-source.mp4').read_bytes() == b'source'


def audit():
    return {'outcome': 'review_failed', 'jev_enabled': True, 'duration_ms': 12000, 'title': 'Original',
        'transcript': [{'start_ms': 0, 'end_ms': 5000, 'text': 'An entire sentence.'}],
        'planner': {'requests': [{'status': 'parsed', 'response': json.dumps({'clips': [
            {'start_time': 0, 'end_time': 5, 'summary': 'A suggestion', 'scores': {'hook': 8}}]})}]}}


def setup_run(tmp_path, monkeypatch):
    for name, data in [('run-history.json', {'status': 'failed', 'jobId': tmp_path.name}),
                       ('edit_audit.json', audit()), ('transcript.json', {'segments': []})]:
        (tmp_path / name).write_text(json.dumps(data))
    (tmp_path / 'editor-source.mp4').write_bytes(b'source')
    monkeypatch.setattr(recover_review, 'source_info', lambda _: {'duration': 12000, 'width': 2160, 'height': 3840})


def test_old_run_recovers_without_ai_or_replacing_failure_evidence(tmp_path, monkeypatch):
    setup_run(tmp_path, monkeypatch)
    original_record = (tmp_path / 'run-history.json').read_bytes()
    original_audit = (tmp_path / 'edit_audit.json').read_bytes()
    async def preview(source, dest, **kwargs): Path(dest).write_bytes(b'preview')
    monkeypatch.setattr(recover_review, 'RenderingService', lambda: SimpleNamespace(capture_framing_source=preview))
    project = asyncio.run(recover_review.recover(tmp_path))
    assert project['candidates'][0]['review'] is None
    assert project['candidates'][0]['status'] == 'refining'
    assert project['candidates'][0]['captions'] is False
    assert project['candidates'][0]['ranges'] == [[0, 5000]]
    assert (tmp_path / 'run-history.json').read_bytes() == original_record
    assert (tmp_path / 'edit_audit.json').read_bytes() == original_audit
    output = json.loads((tmp_path / 'job_output.json').read_text())
    assert output['editor_project'] and output['metrics']['planned_clip_count'] == 1
    assert output['metrics']['recovery'] == {'offline': True, 'from_checkpoint': False}
    with pytest.raises(ValueError, match='already has a result'):
        asyncio.run(recover_review.recover(tmp_path))


def test_recovery_resumes_checkpoint_without_replanning(tmp_path, monkeypatch):
    setup_run(tmp_path, monkeypatch)
    project = recover_review.reconstruct_project(audit(), recover_review.source_info(None), aspect_ratio='16:9', captions=True)
    project['candidates'][0]['title'] = 'Already reviewed'
    (tmp_path / 'editor-project.json').write_text(json.dumps(project))
    (tmp_path / 'edit_audit.json').unlink()
    (tmp_path / 'editor-preview.mp4').write_bytes(b'preview')
    monkeypatch.setattr(recover_review, 'RenderingService', lambda: pytest.fail('Must reuse saved preview'))
    recovered = asyncio.run(recover_review.recover(tmp_path))
    assert recovered['candidates'] == project['candidates']
    assert recovered['aspect_ratio'] == '16:9'


def test_failed_recovery_never_publishes_a_ready_project(tmp_path, monkeypatch):
    setup_run(tmp_path, monkeypatch)
    monkeypatch.setattr(recover_review, 'RenderingService', lambda: SimpleNamespace(
        capture_framing_source=AsyncMock(side_effect=RenderingError('failed'))))
    with pytest.raises(RenderingError):
        asyncio.run(recover_review.recover(tmp_path))
    assert (tmp_path / 'editor-project.json').is_file()
    assert not (tmp_path / 'job_output.json').exists()
