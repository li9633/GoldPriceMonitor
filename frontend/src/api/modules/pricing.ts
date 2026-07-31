import request from '@/api/request'

export interface PricingItem {
  id: number
  provider_name: string
  model_name: string
  input_price: number
  output_price: number
  currency: string
  updated_at: string
}

export interface PricingUpsert {
  input_price?: number
  output_price?: number
  currency?: string
}

export interface PricingPatch {
  input_price?: number
  output_price?: number
  currency?: string
}

export const pricingApi = {
  list() {
    return request.get<PricingItem[]>('/pricing')
  },

  upsert(providerName: string, modelName: string, data: PricingUpsert) {
    return request.put<PricingItem>(
      `/pricing/${encodeURIComponent(providerName)}/${encodeURIComponent(modelName)}`,
      data,
    )
  },

  patch(id: number, data: PricingPatch) {
    return request.patch<PricingItem>(`/pricing/${id}`, data)
  },

  remove(id: number) {
    return request.delete<null>(`/pricing/${id}`)
  },
}
