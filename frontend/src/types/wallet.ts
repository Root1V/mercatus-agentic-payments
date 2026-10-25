export type WalletBackend = "local" | "circle" | "aibank";

// AIBank (RM-18): "omnibus" = modelo A (sub-cuenta bajo la cuenta maestra de
// Mercatus); "mandate" = modelo B (la cuenta propia del cliente, con un
// permiso que el titular aprobó en la app del banco).
export type AibankModel = "omnibus" | "mandate";

export interface WalletSettings {
  backend: WalletBackend;
  // El API key nunca se devuelve -- autentica solo, como un password, no es
  // un identificador público. Mismo tratamiento que el entity secret y que
  // el API key de AIBank (RM-18).
  has_circle_api_key: boolean;
  has_circle_entity_secret: boolean;
  circle_wallet_id: string | null;
  // AIBank (RM-18): solo aplica con el protocolo AP2 -- el riel de AP2 se
  // resuelve en cada request, así que cambiarlo no requiere reiniciar.
  aibank_account_id: string | null;
  has_aibank_api_key: boolean;
  aibank_model: AibankModel;
  // Solo lo escribe el backend al activar un permiso ya aprobado -- nunca
  // se manda desde el formulario.
  aibank_mandate_id: string | null;
  aibank_mandate_account_id: string | null;
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
  aibank_model?: AibankModel;
}
