import { defineStore } from 'pinia'
import { ref } from 'vue'

const TOKEN_KEY = 'petops.admin.token'
const USER_KEY = 'petops.admin.user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const username = ref<string | null>(localStorage.getItem(USER_KEY))

  function setAuth(t: string, u: string) {
    token.value = t
    username.value = u
    localStorage.setItem(TOKEN_KEY, t)
    localStorage.setItem(USER_KEY, u)
  }

  function clear() {
    token.value = null
    username.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, username, setAuth, clear }
})
