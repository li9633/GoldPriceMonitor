import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/layout/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashBoard.vue'),
      },
      {
        path: 'price-history',
        name: 'price-history',
        component: () => import('@/views/PriceHistory.vue'),
      },
      {
        path: 'providers',
        name: 'providers',
        component: () => import('@/views/ProviderList.vue'),
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SystemSettings.vue'),
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/LogViewer.vue'),
      },
      {
        path: 'ai-stats',
        name: 'ai-stats',
        component: () => import('@/views/AiStats.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
