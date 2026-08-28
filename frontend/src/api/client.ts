import axios from "axios";

const TOKEN_STORAGE_KEY = "agent_commerce_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

// Rutas relativas: en dev, vite.config.ts hace de proxy hacia el backend
// nativo; en producción (Docker), nginx.conf hace lo mismo -- así nunca
// hace falta CORS ni una URL de API hardcodeada.
export const apiClient = axios.create({ baseURL: "/" });

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearStoredToken();
      // axios corre fuera del árbol de React (interceptor global), así que
      // no hay un router al que pedirle que navegue -- una redirección dura
      // es la forma correcta de volver a /login desde aquí.
      if (window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);
