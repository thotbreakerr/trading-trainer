// The committed manifest of guided-pointer targets available inside the
// lesson takeover. Lesson YAML `pointer.target` values must appear here —
// backend/tests/test_pointer_targets.py cross-checks the two files.
export const POINTER_TARGETS = [
  'tf-1m',
  'tf-5m',
  'tf-15m',
  'tf-1h',
  'replay-play',
  'replay-step',
  'replay-restart',
] as const

export type PointerTarget = (typeof POINTER_TARGETS)[number]
