"""Recover a failed review run using local artifacts only, never provider calls."""
import argparse
import asyncio
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from clip_engine.services.intelligence_planner import IntelligencePlannerService
from clip_engine.services.manual_editor import (
    atomic_json, default_crop, local_file, read_json, source_info, utf16_prefix, validate_candidate,
)
from clip_engine.services.rendering_service import RenderingService
from clip_engine.services.s3_upload_service import JobOutput
from clip_engine.services.transcription_service import TranscriptSegment


def reconstruct_project(audit, info, *, aspect_ratio, captions):
    """Old versions lost Jev/framing results; restore suggestions as unreviewed."""
    if audit.get('outcome') != 'review_failed' or audit.get('jev_enabled') is not True:
        raise ValueError('Expected a failed Jev review run')
    transcript = [TranscriptSegment(s['start_ms'], s['end_ms'], s['text'], s.get('speaker'))
                  for s in audit['transcript']]
    duration = audit['duration_ms']
    if abs(duration - info['duration']) > 100:
        raise ValueError('Saved plan does not match the source duration')
    saved = [r for r in audit['planner']['requests'] if r.get('status') == 'parsed' and r.get('response')]
    if len(saved) != 1:
        raise ValueError('Expected exactly one completed clip plan')
    # Use the same boundary/anchor validation as the original run. Constructing
    # just the parser avoids loading provider credentials or any API client.
    planner = IntelligencePlannerService.__new__(IntelligencePlannerService)
    planner.settings = SimpleNamespace(planner_max_output_tokens=0)
    planner._jev_enabled = True
    planner._current_transcript = transcript
    planner._current_video_duration = duration / 1000
    plan = planner._parse_clip_plan_response({'choices': [
        {'message': {'content': saved[0]['response']}, 'finish_reason': 'stop'}]})
    if not plan.segments:
        raise ValueError('No recoverable clip suggestions')
    w, h = info['width'], info['height']
    aspect = 9 / 16 if aspect_ratio == '9:16' else 16 / 9
    project = {'version': 1, 'revision': 0, 'title': utf16_prefix(audit.get('title') or 'Recovered project', 1024),
               'width': w, 'height': h, 'duration_ms': duration, 'aspect_ratio': aspect_ratio,
               'transcript': [{'start_ms': s.start_time_ms, 'end_ms': s.end_time_ms,
                               'text': utf16_prefix(s.text, 20000)} for s in transcript], 'candidates': []}
    segments = planner._finalize_clips(plan.segments, 100, allow_alternatives=bool(transcript))
    for i, segment in enumerate(segments[:100]):
        candidate = {'id': f'candidate-{i + 1}', 'title': utf16_prefix(segment.summary or f'Clip {i + 1}', 200),
                     'ranges': [[segment.start_time_ms, segment.end_time_ms]],
                     'scenes': [{'at_ms': 0, 'layout': 'fit', 'crops': [default_crop(w, h, aspect)]}],
                     'score': max(0, min(100, segment.virality_score)), 'reason': '',
                     'requires_visual_context': bool((segment.moment or {}).get('requires_visual_context')),
                     'captions': captions, 'caption_preset': 'pop', 'video_speed': 1,
                     'exports': [], 'review': None, 'status': 'refining',
                     'caption_edits': [], 'caption_suppression_ranges': []}
        validate_candidate(candidate, duration, len(transcript))
        project['candidates'].append(candidate)
    return project


async def recover(run, *, aspect_ratio='9:16', captions=False, progress=None):
    run = Path(run).resolve(strict=True)
    if (run / 'job_output.json').exists():
        raise ValueError('This run already has a result; refusing to replace it')
    record = read_json(run, 'run-history.json', 16384)
    if record.get('status') not in ('failed', 'cancelled') or record.get('jobId') != run.name:
        raise ValueError('Only a stopped, failed review run can be recovered')
    source = local_file(run, 'editor-source.mp4')
    info = await asyncio.to_thread(source_info, source)
    checkpoint = (run / 'editor-project.json').exists()
    project = read_json(run, 'editor-project.json') if checkpoint else reconstruct_project(
        read_json(run, 'edit_audit.json'), info, aspect_ratio=aspect_ratio, captions=captions)
    if project.get('source_id') or project.get('preview_id') or project.get('media_freed'):
        raise ValueError('Recovery is only for initial project preparation')
    if abs(project['duration_ms'] - info['duration']) > 100:
        raise ValueError('Project does not match the source duration')
    for candidate in project['candidates']:
        validate_candidate(candidate, project['duration_ms'], len(project['transcript']))
    local_file(run, 'transcript.json')
    atomic_json(run / 'editor-project.json', project)
    preview = run / 'editor-preview.mp4'
    if not preview.exists():
        await RenderingService().capture_framing_source(str(source), str(preview),
            progress=progress, duration_ms=project['duration_ms'])
    preview_info = await asyncio.to_thread(source_info, local_file(run, 'editor-preview.mp4'))
    if (abs(preview_info['duration'] - info['duration']) > 100 or
            abs(preview_info['width'] / preview_info['height'] / (info['width'] / info['height']) - 1) > .01):
        raise ValueError('Preview does not match the source')
    project['frame_preview'] = True
    atomic_json(run / 'editor-project.json', project)
    output = JobOutput(job_id=run.name, source_video_url=str(source),
        source_video_title=project['title'] + ' (recovered)', source_video_duration_seconds=project['duration_ms'] / 1000,
        total_clips=0, clips=[], editor_project=True, transcript_url=str(run / 'transcript.json'),
        metrics={'planned_clip_count': len(project['candidates']),
                 'recovery': {'offline': True, 'from_checkpoint': checkpoint},
                 'api_costs': {'cost_incomplete': True}})
    # Publish last. Keep the original failure record and audit as evidence.
    atomic_json(run / 'job_output.json', asdict(output))
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--aspect-ratio', choices=['9:16', '16:9'], default='9:16')
    parser.add_argument('--captions', action='store_true')
    args = parser.parse_args()
    project = asyncio.run(recover(args.run, aspect_ratio=args.aspect_ratio, captions=args.captions,
        progress=lambda p: print(f'Preparing preview: {p}%', flush=True)))
    print(f"Recovered {len(project['candidates'])} editable candidates without API calls.")


if __name__ == '__main__':
    main()
