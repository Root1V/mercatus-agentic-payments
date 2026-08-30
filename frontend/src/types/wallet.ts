export type WalletBackend = "local" | "circle" | "aibank";

export interface WalletSettings {
  backend: WalletBackend;
  // El API key nunca se devuelve -- autentica solo, como un password, no es
  // un identificador público. Mismo tratamiento que el entity secret y que
  // el API key de AIBank (RM-18).
  has_circle_api_key: boolean;
  has_circle_entity_secret: boolean;
  circle_wallet_id: string | null;
  // AIBank (RM-18): solo aplica con el protocolo AP2, y solo si el
  // dashboard se inició con AGENT_COMMERCE_AP2_SETTLEMENT=aibank (el riel
  // de liquidación de AP2 queda fijo al arrancar el proceso).
  aibank_account_id: string | null;
  has_aibank_api_key: boolean;
  updated_at: string | null;
}

export interface UpdateWalletSettingsInput {
  backend: WalletBackend;
  // undefined = conservar el valor ya guardado (para poder editar el resto
  // sin reescribirlos).
  circle_api_key?: string;
  circle_entity_secret?: string;
  circle_wallet_id?: string | null;
  aibank_account_id?: string | null;
  aibank_api_key?: string;
}
