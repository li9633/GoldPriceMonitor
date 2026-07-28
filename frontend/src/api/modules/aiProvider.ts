import request from '@/api/request'

export interface ModelProvider {
  id: number
  name: string
  api_url: string
  api_key: string
  timeout: number
  sort_order: number
  models: string[]
}

export interface ProviderModel {
  id: number
  provider_name: string
  model_name: string
  sort_order: number
}

export interface ProviderCreate {
  name: string
  api_url: string
  api_key: string
  timeout?: number
  sort_order?: number
}

export interface ProviderUpdate {
  name?: string
  api_url?: string
  api_key?: string
  timeout?: number
  sort_order?: number
}

export interface ProviderModelCreate {
  provider_name: string
  model_name: string
  sort_order?: number
}

export interface ProviderModelUpdate {
  model_name?: string
  sort_order?: number
}

export const providerApi = {
  list() {
    return request.get<ModelProvider[]>('/providers')
  },
  get(name: string) {
    return request.get<ModelProvider>(`/providers/${name}`)
  },
  create(data: ProviderCreate) {
    return request.post<ModelProvider>('/providers', data)
  },
  update(name: string, data: ProviderUpdate) {
    return request.put<ModelProvider>(`/providers/${name}`, data)
  },
  remove(name: string) {
    return request.delete<null>(`/providers/${name}`)
  },
  listModels(name: string) {
    return request.get<ProviderModel[]>(`/providers/${name}/models`)
  },
  createModel(name: string, data: ProviderModelCreate) {
    return request.post<ProviderModel>(`/providers/${name}/models`, data)
  },
  updateModel(name: string, modelId: number, data: ProviderModelUpdate) {
    return request.put<ProviderModel>(`/providers/${name}/models/${modelId}`, data)
  },
  removeModel(name: string, modelId: number) {
    return request.delete<null>(`/providers/${name}/models/${modelId}`)
  },
}
