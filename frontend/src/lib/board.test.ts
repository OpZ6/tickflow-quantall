// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { getBoardType } from './board'

describe('getBoardType', () => {
  it.each([
    ['600000.SH', '沪主板'],
    ['003001.SZ', '深主板'],
    ['302132.SZ', '创业板'],
    ['689009.SH', '科创板'],
    ['920001.BJ', '北交所'],
    ['999999.SZ', null],
  ] as const)('%s => %s', (symbol, board) => {
    expect(getBoardType(symbol)).toBe(board)
  })
})
