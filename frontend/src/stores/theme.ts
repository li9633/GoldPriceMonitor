import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type Theme = 'light' | 'dark'

export const useThemeStore = defineStore('theme', () => {
  const current = ref<Theme>((localStorage.getItem('app-theme') as Theme) || 'light')

  const applyTheme = (theme: Theme) => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('app-theme', theme)
  }

  const toggle = () => {
    current.value = current.value === 'light' ? 'dark' : 'light'
  }

  const setTheme = (theme: Theme) => {
    current.value = theme
  }

  applyTheme(current.value)

  watch(current, (val) => applyTheme(val))

  return { current, toggle, setTheme }
})
