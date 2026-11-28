/**
 * 「换手—收益拥挤密度」的色阶分档。
 *
 * 该矩阵的计数极度右偏：同一张 90 格里既有 600 只以上的热点格，也有 1~2 只的
 * 边角格（实测样本 5576 只，中位数 16 只、最大 618 只）。两种连续色阶都不好用：
 *   - 线性色阶：几乎全部格子落在低段，压成同一个深色，看不出结构；
 *   - log10 色阶：低段是被拉亮了，但中位数 16 只会被抬到色带 44% 处，
 *     配上「暗蓝→琥珀→红」的暖色终点，整张图就变成一片红。
 *
 * 所以改成固定几何分档：颜色只在跨档时跳变，红色只留给 300+ 的真正热点格。
 * 阈值写死、不随当日分布漂移，跨日可比；图例直接标出真实股票数区间。
 */

export type DensityPiece = {
  value?: number
  gte?: number
  lte?: number
  label: string
  color: string
}

export type DensityTheme = 'dark' | 'light'

/** 非零档的上界，最后再加一个开区间档（300+）。 */
const DENSITY_CUTS = [10, 30, 100, 300] as const

/** 空档(0 只)不参与热度排序, 只做「这里没有样本」的底色, 因此贴着卡片底色走。 */
const DENSITY_ZERO: Record<DensityTheme, string> = { dark: '#121a28', light: '#f1f3f6' }

/** 暗蓝 → 蓝 → 青 → 琥珀 → 红(暗色) / 浅蓝 → 蓝 → 青 → 琥珀 → 红(亮色), 逐档加亮。 */
const DENSITY_COLORS: Record<DensityTheme, readonly string[]> = {
  dark: ['#1c3550', '#275f88', '#2f8fa8', '#c9971f', '#ef5b4a'],
  light: ['#cfe0ee', '#9dc2dd', '#5f9dbf', '#d9a12c', '#d94a35'],
}

export function densityPieces(theme: DensityTheme = 'dark'): DensityPiece[] {
  const colors = DENSITY_COLORS[theme]
  const pieces: DensityPiece[] = [{ value: 0, label: '0', color: DENSITY_ZERO[theme] }]
  let lower = 1
  DENSITY_CUTS.forEach((cut, index) => {
    const upper = cut - 1
    pieces.push({
      gte: lower,
      lte: upper,
      label: lower === upper ? String(lower) : `${lower}-${upper}`,
      color: colors[index],
    })
    lower = cut
  })
  pieces.push({ gte: lower, label: `${lower}+`, color: colors[DENSITY_CUTS.length] })
  return pieces
}

/** 按档位取色，供图例之外的场合（如 tooltip 色块）复用。 */
export function densityColor(count: number | null | undefined, theme: DensityTheme = 'dark'): string {
  if (count == null || count <= 0) return DENSITY_ZERO[theme]
  const colors = DENSITY_COLORS[theme]
  const index = DENSITY_CUTS.findIndex((cut) => count < cut)
  return index === -1 ? colors[DENSITY_CUTS.length] : colors[index]
}
