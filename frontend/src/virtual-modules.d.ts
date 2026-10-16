declare module 'virtual:quantx-portable-runtime' {
  const runtime: string
  export default runtime
}

interface Window {
  __QUANTX_PORTABLE__?: boolean
}
