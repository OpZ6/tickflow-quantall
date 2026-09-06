import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { toast } from '@/components/Toast'
import { api, type PipelineJob } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

/**
 * Start (or join) the single-flight market data pipeline from any data panel.
 * A successful full refresh invalidates every consumer because daily data,
 * enriched data, indexes, derived panels and QuantX are published together.
 */
export function usePipelineRefresh() {
  const queryClient = useQueryClient()
  const [requestedJobId, setRequestedJobId] = useState<string | null>(null)
  const handledJobId = useRef<string | null>(null)

  const jobs = useQuery({
    queryKey: QK.pipelineJobs,
    queryFn: () => api.pipelineJobs(1),
    refetchInterval: query => query.state.data?.active_id ? 1_000 : 15_000,
  })
  const jobId = requestedJobId || jobs.data?.active_id || null
  const job = useQuery({
    queryKey: QK.pipelineJob(jobId || ''),
    queryFn: () => api.pipelineJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: query => {
      const current = query.state.data
      return current && (current.status === 'succeeded' || current.status === 'failed') ? false : 1_000
    },
  })
  const start = useMutation({
    mutationFn: api.pipelineRun,
    onSuccess: ({ job_id }) => {
      handledJobId.current = null
      setRequestedJobId(job_id)
    },
    onError: (error: Error) => toast(`数据更新启动失败：${error.message}`, 'error'),
  })

  useEffect(() => {
    const current = job.data
    if (!current || !['succeeded', 'failed'].includes(current.status)) return
    if (handledJobId.current === current.id) return
    handledJobId.current = current.id

    if (current.status === 'succeeded') {
      void queryClient.invalidateQueries().then(() => {
        const tradeDate = current.result?.quantx?.trade_date
        toast(tradeDate ? `数据已更新至 ${tradeDate}` : '市场数据已更新', 'success')
      })
    } else {
      toast(`数据更新失败：${current.error || '请查看数据页任务日志'}`, 'error')
    }
    void queryClient.invalidateQueries({ queryKey: QK.pipelineJobs })
    setRequestedJobId(null)
  }, [job.data, queryClient])

  const refresh = () => {
    if (jobId) {
      setRequestedJobId(jobId)
      return
    }
    start.mutate()
  }

  return {
    refresh,
    isRefreshing: start.isPending || job.data?.status === 'pending' || job.data?.status === 'running',
    job: job.data as PipelineJob | undefined,
  }
}
