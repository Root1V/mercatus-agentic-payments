export type WalletBackend = "local" | "circle";

export interface WalletSettings {
  backend: WalletBackend;
  // El API key nunca se devuelve -- autentica solo, como un password, no es
  // un identificador público. Mismo tratamiento que el entity secret.
  has_circle_api_key: boolean;
  has_circle_entity_secret: boolean;
  circle_wallet_id: string | null;
  updated_at: string | null;
}

export interface UpdateWalletSettingsInput {
  backend: WalletBackend;
  // undefined = conservar el valor ya guardado (para poder editar el resto
  // sin reescribirlos).
  circle_api_key?: string;
  circle_entity_secret?: string;
  circle_wallet_id?: string | null;
}
