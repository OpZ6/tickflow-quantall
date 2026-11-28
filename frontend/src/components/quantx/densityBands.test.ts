// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { densityColor, densityPieces } from './densityBands'

describe('densityPieces', () => {
  it('给出 0 档 + 5 个非零档，覆盖 1 只到 300+', () => {
    const pieces = densityPieces()
    expect(pieces).toHaveLength(6)
    expect(pieces[0]).toMatchObject({ value: 0, label: '0' })
    expect(pieces.slice(1).map((piece) => piece.label)).toEqual([
      '1-9',
      '10-29',
      '30-99',
      '100-299',
      '300+',
    ])
  })

  it('非零档首尾相接，不留空档也不重叠', () => {
    const nonZero = densityPieces().slice(1)
    expect(nonZero[0].gte).toBe(1)
    for (let index = 1; index < nonZero.length; index += 1) {
      expect(nonZero[index].gte).toBe((nonZero[index - 1].lte as number) + 1)
    }
    expect(nonZero[nonZero.length - 1].lte).toBeUndefined()
  })

  it('色阶逐档变化，最高档才用红', () => {
    for (const theme of ['dark', 'light'] as const) {
      const colors = densityPieces(theme).map((piece) => piece.color)
      expect(new Set(colors).size).toBe(6)
      expect(colors[colors.length - 1]).toBe(theme === 'dark' ? '#ef5b4a' : '#d94a35')
    }
  })

  it('空档底色跟着主题走，亮色下不会变成黑块', () => {
    expect(densityPieces('dark')[0].color).toBe('#121a28')
    expect(densityPieces('light')[0].color).toBe('#f1f3f6')
  })
})

describe('densityColor', () => {
  it.each([
    [null, '#121a28'],
    [0, '#121a28'],
    [1, '#1c3550'],
    [9, '#1c3550'],
    [10, '#275f88'],
    [29, '#275f88'],
    [30, '#2f8fa8'],
    [99, '#2f8fa8'],
    [100, '#c9971f'],
    [299, '#c9971f'],
    [300, '#ef5b4a'],
    [618, '#ef5b4a'],
  ])('暗色下计数 %s 取色 %s', (count, expected) => {
    expect(densityColor(count)).toBe(expected)
  })

  it('亮色下最低档是浅蓝', () => {
    expect(densityColor(3, 'light')).toBe('#cfe0ee')
    expect(densityColor(500, 'light')).toBe('#d94a35')
  })
})
