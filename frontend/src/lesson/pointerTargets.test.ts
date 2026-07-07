// Manifest sanity — the backend cross-checks lesson YAML against this list
// (backend/tests/test_pointer_targets.py); this guards the list itself.
import { describe, expect, it } from 'vitest'
import { POINTER_TARGETS } from './pointerTargets'

describe('POINTER_TARGETS', () => {
  it('is non-empty', () => {
    expect(POINTER_TARGETS.length).toBeGreaterThan(0)
  })

  it('has unique ids', () => {
    expect(new Set(POINTER_TARGETS).size).toBe(POINTER_TARGETS.length)
  })

  it('uses kebab-case ids', () => {
    for (const id of POINTER_TARGETS) {
      expect(id).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/)
    }
  })
})
