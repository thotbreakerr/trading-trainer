import { describe, expect, it } from 'vitest'
import { parseRoute } from './routing'

describe('parseRoute', () => {
  it('maps lifecycle routes', () => {
    expect(parseRoute('/today/plan')).toMatchObject({ tab: 'market', phase: 'plan' })
    expect(parseRoute('/today/review/')).toMatchObject({ tab: 'market', phase: 'review' })
  })

  it('maps learn sections and modules', () => {
    expect(parseRoute('/learn/drills')).toMatchObject({ tab: 'learn', section: 'drills' })
    expect(parseRoute('/learn/module/7')).toMatchObject({
      tab: 'learn',
      section: 'curriculum',
      moduleNumber: 7,
    })
  })

  it('maps journal details and falls back safely', () => {
    expect(parseRoute('/journal/42')).toMatchObject({ tab: 'journal', tradeId: 42 })
    expect(parseRoute('/not-a-route')).toMatchObject({ tab: 'market', phase: 'trade' })
  })
})
