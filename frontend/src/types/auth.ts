export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
}

export interface CurrentUser {
  id: number;
  username: string;
  is_active: boolean;
}
