import { http } from './client'

export interface LoginResponse {
  token: string
  username: string
}

export interface MeResponse {
  username: string
}

export const authApi = {
  login: (username: string, password: string) =>
    http.post<LoginResponse>('/login', { username, password }).then((r) => r.data),
  logout: () => http.post('/logout').then(() => undefined),
  me: () => http.get<MeResponse>('/me').then((r) => r.data)
}
