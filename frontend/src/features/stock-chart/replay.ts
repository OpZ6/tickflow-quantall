/** 返回回放时点可见的不可变前缀，绝不把未来 candles 交给后续计算。 */
export function rowsAtReplay<T>(rows: readonly T[], replayIndex: number | null): T[] {
  if (replayIndex == null) return [...rows]
  return rows.slice(0, Math.max(0, replayIndex) + 1)
}
