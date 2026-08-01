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
        meta: {
          title: '仪表盘',
        },
      },
      {
        path: 'price-history',
        name: 'price-history',
        component: () => import('@/views/PriceHistory.vue'),
        meta: {
          title: '价格历史',
        },
      },
      {
        path: 'providers',
        name: 'providers',
        component: () => import('@/views/ProviderList.vue'),
        meta: {
          title: 'AI模型池',
        },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SystemSettings.vue'),
        meta: {
          title: '系统设置',
        },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/LogViewer.vue'),
        meta: {
          title: '系统日志',
        },
      },
      {
        path: 'ai-stats',
        name: 'ai-stats',
        component: () => import('@/views/AiStats.vue'),
        meta: {
          title: 'AI模调用统计',
        },
      },
      {
        path: 'notification-stats',
        name: 'notification-stats',
        component: () => import('@/views/NotificationStats.vue'),
        meta: {
          title: '通知统计',
        },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  if (to.meta.title) {
    document.title = (to.meta.title as string) + ' - Gold Price Monitor'
  }
})

export default router
