#include "cm1_bridge.h"

#include <cerrno>
#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/core/version.h"

#if ESPHOME_VERSION_CODE >= VERSION_CODE(2026, 1, 0)
#include <span>
#endif

namespace esphome {
namespace cm1_bridge {

static const char *const TAG = "cm1_bridge";
static const size_t MAX_QUEUE = 32;
static const size_t MAX_PENDING = 4096;
static const size_t MAX_TX_LENGTH = 60;

// ---------------------------------------------------------------------------- cycle de vie
void CM1Bridge::setup() {
  struct sockaddr_storage bind_addr;
  socklen_t bind_addrlen =
      socket::set_sockaddr_any(reinterpret_cast<struct sockaddr *>(&bind_addr), sizeof(bind_addr), this->port_);
#if ESPHOME_VERSION_CODE >= VERSION_CODE(2026, 3, 0)
  this->socket_ = socket::socket_ip_loop_monitored(SOCK_STREAM, PF_INET);
#else
  this->socket_ = socket::socket_ip(SOCK_STREAM, PF_INET);
#endif
  if (this->socket_ == nullptr) {
    ESP_LOGE(TAG, "Impossible de créer la socket");
    this->mark_failed();
    return;
  }
  this->socket_->setblocking(false);
  if (this->socket_->bind(reinterpret_cast<struct sockaddr *>(&bind_addr), bind_addrlen) != 0) {
    ESP_LOGE(TAG, "bind() a échoué sur le port %u (errno %d)", this->port_, errno);
    this->mark_failed();
    return;
  }
  this->socket_->listen(4);
  this->publish_sensors_();
}

void CM1Bridge::loop() {
  this->read_uart_();
  this->accept_();
  this->read_clients_();
  this->write_uart_();
  this->flush_clients_();
  this->cleanup_clients_();

  // sortie automatique de maintenance si plus aucun client
  if (this->maintenance_ && this->clients_.empty() && this->maint_timeout_ms_ > 0 && this->no_client_since_ != 0 &&
      millis() - this->no_client_since_ > this->maint_timeout_ms_) {
    ESP_LOGW(TAG, "Aucun client depuis %u s : sortie automatique du mode maintenance",
             (unsigned) (this->maint_timeout_ms_ / 1000));
    this->set_maintenance_(false);
  }
}

void CM1Bridge::dump_config() {
  ESP_LOGCONFIG(TAG, "CM1 Bridge:");
  ESP_LOGCONFIG(TAG, "  Port TCP : %u", this->port_);
  ESP_LOGCONFIG(TAG, "  Clients max : %u, espacement min : %u ms, délai maintenance : %u s", this->max_clients_,
                (unsigned) this->min_spacing_ms_, (unsigned) (this->maint_timeout_ms_ / 1000));
  ESP_LOGCONFIG(TAG, "  Réseaux autorisés : %u (0 = tous)", (unsigned) this->allowed_.size());
#ifdef USE_BINARY_SENSOR
  LOG_BINARY_SENSOR("  ", "Connecté :", this->connected_sensor_);
#endif
#ifdef USE_SENSOR
  LOG_SENSOR("  ", "Clients :", this->connection_count_sensor_);
#endif
}

void CM1Bridge::on_shutdown() {
  for (auto &client : this->clients_)
    client.socket->shutdown(SHUT_RDWR);
  this->socket_ = nullptr;
}

// ---------------------------------------------------------------------------- UART
void CM1Bridge::read_uart_() {
  uint8_t c;
  while (this->available() > 0 && this->read_byte(&c)) {
    if (c == '\r' || c == '\n') {
      if (!this->rx_line_.empty()) {
        std::string line;
        line.swap(this->rx_line_);
        ESP_LOGD(TAG, "< %s", line.c_str());
        this->broadcast_("RX " + std::to_string(millis()) + " " + line + "\n");
        this->on_line_.call(line);
      }
    } else if (c >= 32 && c < 127 && this->rx_line_.size() < this->max_line_length_) {
      this->rx_line_ += (char) c;
    }
  }
}

void CM1Bridge::write_uart_() {
  if (this->tx_local_.empty() && this->tx_clients_.empty())
    return;
  const uint32_t now = millis();
  if (now - this->last_tx_ms_ < this->next_tx_delay_ms_)
    return;
  TxItem item;
  if (!this->tx_local_.empty()) {
    item = std::move(this->tx_local_.front());
    this->tx_local_.pop_front();
  } else {
    item = std::move(this->tx_clients_.front());
    this->tx_clients_.pop_front();
  }
  std::string out = item.line + "\r";
  this->write_array(reinterpret_cast<const uint8_t *>(out.data()), out.size());
  ESP_LOGD(TAG, "> [%s] %s", item.origin.c_str(), item.line.c_str());
  this->broadcast_("TX " + std::to_string(now) + " " + item.origin + " " + item.line + "\n");
  this->last_tx_ms_ = now;
  // espacement : temps d'émission de la ligne (10 bits par octet) + marge configurée
  uint32_t baud = this->parent_ != nullptr ? this->parent_->get_baud_rate() : 38400;
  if (baud == 0)
    baud = 38400;
  this->next_tx_delay_ms_ = this->min_spacing_ms_ + (uint32_t) (out.size() * 10000UL / baud);
}

bool CM1Bridge::send_local(const std::string &line) {
  std::string l = trim_(line);
  if (l.empty())
    return false;
  if (this->maintenance_ && l != "*" && l != "*1") {
    ESP_LOGW(TAG, "Envoi local refusé en maintenance : %s", l.c_str());
    return false;
  }
  if (this->tx_local_.size() >= MAX_QUEUE) {
    ESP_LOGW(TAG, "File locale pleine, ligne ignorée : %s", l.c_str());
    return false;
  }
  this->tx_local_.push_back({l, "LOCAL"});
  return true;
}

void CM1Bridge::set_busy(bool busy) {
  if (busy == this->busy_)
    return;
  this->busy_ = busy;
  this->broadcast_(this->state_line_());
}

void CM1Bridge::set_alarm(bool alarm) { this->alarm_ = alarm; }

// ---------------------------------------------------------------------------- maintenance
bool CM1Bridge::request_maintenance(bool on) {
  if (on == this->maintenance_)
    return true;
  if (on) {
    if (this->busy_) {
      this->broadcast_("EVT " + std::to_string(millis()) + " MAINT REFUSED MOVING\n");
      ESP_LOGW(TAG, "Maintenance refusée : mouvement ou démarrage en cours");
      return false;
    }
    if (this->alarm_) {
      this->broadcast_("EVT " + std::to_string(millis()) + " MAINT REFUSED ALARM\n");
      ESP_LOGW(TAG, "Maintenance refusée : moteur en alarme");
      return false;
    }
  }
  this->set_maintenance_(on);
  return true;
}

void CM1Bridge::set_maintenance_(bool on) {
  this->maintenance_ = on;
  if (on) {
    this->tx_clients_.clear();
    this->no_client_since_ = this->clients_.empty() ? millis() : 0;
  } else {
    this->tx_clients_.clear();
    this->no_client_since_ = 0;
  }
  ESP_LOGI(TAG, "Mode %s", on ? "MAINTENANCE" : "NORMAL");
  this->broadcast_(this->state_line_());
#ifdef USE_SWITCH
  if (this->maintenance_switch_ != nullptr)
    this->maintenance_switch_->publish_state(on);
#endif
}

std::string CM1Bridge::state_line_() const {
  return "EVT " + std::to_string(millis()) + " STATE " + (this->maintenance_ ? "MAINT" : "NORMAL") + " " +
         (this->busy_ ? "1" : "0") + "\n";
}

// ---------------------------------------------------------------------------- clients
bool CM1Bridge::ip_allowed_(uint32_t ip) const {
  if (this->allowed_.empty())
    return true;
  for (const auto &n : this->allowed_) {
    if ((ip & n.mask) == (n.network & n.mask))
      return true;
  }
  return false;
}

void CM1Bridge::accept_() {
  if (this->socket_ == nullptr)
    return;
  struct sockaddr_storage client_addr;
  socklen_t client_addrlen = sizeof(client_addr);
  std::unique_ptr<socket::Socket> sock =
      this->socket_->accept(reinterpret_cast<struct sockaddr *>(&client_addr), &client_addrlen);
  if (!sock)
    return;
#if ESPHOME_VERSION_CODE >= VERSION_CODE(2026, 1, 0)
  std::string identifier = std::string(socket::SOCKADDR_STR_LEN, 0);
  auto span = std::span<char, socket::SOCKADDR_STR_LEN>(identifier.data(), identifier.size());
  identifier.resize(sock->getpeername_to(span));
#else
  std::string identifier = sock->getpeername();
#endif
  uint32_t ip = 0;
  if (client_addr.ss_family == AF_INET) {
    ip = ntohl(reinterpret_cast<struct sockaddr_in *>(&client_addr)->sin_addr.s_addr);
  }
  if (!this->ip_allowed_(ip)) {
    ESP_LOGW(TAG, "Connexion refusée depuis %s (hors allowed_ips)", identifier.c_str());
    sock->shutdown(SHUT_RDWR);
    return;
  }
  if (this->clients_.size() >= this->max_clients_) {
    ESP_LOGW(TAG, "Connexion refusée depuis %s : %u clients déjà connectés", identifier.c_str(),
             (unsigned) this->clients_.size());
    sock->shutdown(SHUT_RDWR);
    return;
  }
  sock->setblocking(false);
  uint8_t index = this->next_client_index_++;
  if (this->next_client_index_ == 0)
    this->next_client_index_ = 1;
  this->clients_.emplace_back(std::move(sock), identifier, index);
  this->no_client_since_ = 0;
  ESP_LOGI(TAG, "Client %s connecté depuis %s", this->clients_.back().name().c_str(), identifier.c_str());
  this->send_to_(this->clients_.back(), std::string("HELLO ") + std::to_string(PROTOCOL_VERSION) + " " +
                                           (this->maintenance_ ? "MAINT" : "NORMAL") + " " +
                                           (this->busy_ ? "1" : "0") + "\n");
  this->publish_sensors_();
}

void CM1Bridge::read_clients_() {
  char buf[256];
  for (auto &client : this->clients_) {
    if (client.disconnected)
      continue;
    ssize_t n;
    while ((n = client.socket->read(buf, sizeof(buf))) > 0) {
      for (ssize_t i = 0; i < n; i++) {
        char c = buf[i];
        if (c == '\n') {
          std::string line;
          line.swap(client.rx);
          this->handle_client_line_(client, trim_(line));
        } else if (c != '\r' && client.rx.size() < 512) {
          client.rx += c;
        }
      }
    }
    if (n == 0 || (n < 0 && errno == ECONNRESET)) {
      client.disconnected = true;
    } else if (n < 0 && errno != EWOULDBLOCK && errno != EAGAIN) {
      ESP_LOGW(TAG, "Erreur de lecture client %s (errno %d)", client.name().c_str(), errno);
      client.disconnected = true;
    }
  }
}

void CM1Bridge::handle_client_line_(Client &client, const std::string &line) {
  if (line.empty())
    return;
  const std::string ms = std::to_string(millis());
  if (line == "PING") {
    this->send_to_(client, "PONG\n");
  } else if (line == "STATUS") {
    this->send_to_(client, this->state_line_());
  } else if (line == "MAINT ON") {
    if (this->maintenance_)
      this->send_to_(client, this->state_line_());
    else
      this->request_maintenance(true);
  } else if (line == "MAINT OFF") {
    if (!this->maintenance_)
      this->send_to_(client, this->state_line_());
    else
      this->request_maintenance(false);
  } else if (line.rfind("TX ", 0) == 0) {
    std::string payload = trim_(line.substr(3));
    if (payload.size() > MAX_TX_LENGTH) {
      this->send_to_(client, "ERR " + ms + " TOOLONG " + payload + "\n");
    } else if (!this->maintenance_ && !is_read_only_(payload)) {
      this->send_to_(client, "ERR " + ms + " FORBIDDEN " + payload + "\n");
    } else if (this->tx_clients_.size() >= MAX_QUEUE) {
      this->send_to_(client, "ERR " + ms + " QUEUE_FULL " + payload + "\n");
    } else {
      this->tx_clients_.push_back({payload, client.name()});
    }
  } else {
    this->send_to_(client, "ERR " + ms + " BADCMD " + line + "\n");
  }
}

void CM1Bridge::send_to_(Client &client, const std::string &text) {
  if (client.disconnected)
    return;
  if (!client.pending.empty()) {
    if (client.pending.size() + text.size() > MAX_PENDING) {
      ESP_LOGW(TAG, "Client %s trop lent, données perdues", client.name().c_str());
      return;
    }
    client.pending += text;
    return;
  }
  ssize_t written = client.socket->write(text.data(), text.size());
  if (written < 0) {
    if (errno == EWOULDBLOCK || errno == EAGAIN) {
      client.pending += text;
    } else {
      client.disconnected = true;
    }
  } else if ((size_t) written < text.size()) {
    client.pending += text.substr(written);
  }
}

void CM1Bridge::broadcast_(const std::string &text) {
  for (auto &client : this->clients_)
    this->send_to_(client, text);
}

void CM1Bridge::flush_clients_() {
  for (auto &client : this->clients_) {
    if (client.disconnected || client.pending.empty())
      continue;
    ssize_t written = client.socket->write(client.pending.data(), client.pending.size());
    if (written > 0) {
      client.pending.erase(0, written);
    } else if (written < 0 && errno != EWOULDBLOCK && errno != EAGAIN) {
      client.disconnected = true;
    }
  }
}

void CM1Bridge::cleanup_clients_() {
  bool removed = false;
  for (auto it = this->clients_.begin(); it != this->clients_.end();) {
    if (it->disconnected) {
      ESP_LOGI(TAG, "Client %s déconnecté", it->name().c_str());
      it = this->clients_.erase(it);
      removed = true;
    } else {
      ++it;
    }
  }
  if (removed) {
    if (this->clients_.empty() && this->maintenance_)
      this->no_client_since_ = millis();
    this->publish_sensors_();
  }
}

void CM1Bridge::publish_sensors_() {
#ifdef USE_BINARY_SENSOR
  if (this->connected_sensor_ != nullptr)
    this->connected_sensor_->publish_state(!this->clients_.empty());
#endif
#ifdef USE_SENSOR
  if (this->connection_count_sensor_ != nullptr)
    this->connection_count_sensor_->publish_state(this->clients_.size());
#endif
}

// ---------------------------------------------------------------------------- liste blanche
std::string CM1Bridge::trim_(const std::string &s) {
  size_t a = 0, b = s.size();
  while (a < b && (s[a] == ' ' || s[a] == '\t'))
    a++;
  while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r' || s[b - 1] == '\n'))
    b--;
  return s.substr(a, b - a);
}

static bool is_digits(const std::string &s, size_t from, size_t to) {
  if (from >= to)
    return false;
  for (size_t i = from; i < to; i++)
    if (s[i] < '0' || s[i] > '9')
      return false;
  return true;
}

/// Accepte un suffixe « .id » optionnel à partir de `pos` ; vrai si la fin est valide.
static bool optional_motor_suffix(const std::string &s, size_t pos) {
  if (pos == s.size())
    return true;
  if (s[pos] != '.')
    return false;
  return is_digits(s, pos + 1, s.size());
}

/// Une instruction est une lecture si : ?..., lettre de registre + chiffres, _SKH, * ou *1.
static bool statement_is_read_only(const std::string &st) {
  if (st.empty())
    return false;
  if (st[0] == '?') {
    size_t i = 1;
    while (i < st.size() && isalnum((unsigned char) st[i]))
      i++;
    return optional_motor_suffix(st, i);
  }
  if (st[0] == '*') {
    size_t i = 1;
    if (i < st.size() && st[i] == '1')
      i++;
    return optional_motor_suffix(st, i);
  }
  if (st.rfind("_SKH", 0) == 0)
    return optional_motor_suffix(st, 4);
  char c = toupper((unsigned char) st[0]);
  if (strchr("PSAMTVNRHK", c) != nullptr) {
    size_t i = 1;
    while (i < st.size() && st[i] >= '0' && st[i] <= '9')
      i++;
    if (i == 1)
      return false;
    return optional_motor_suffix(st, i);
  }
  return false;
}

bool CM1Bridge::is_read_only_(const std::string &line) {
  size_t start = 0;
  bool any = false;
  while (start <= line.size()) {
    size_t comma = line.find(',', start);
    std::string part = trim_(line.substr(start, comma == std::string::npos ? std::string::npos : comma - start));
    if (!part.empty()) {
      any = true;
      if (!statement_is_read_only(part))
        return false;
    }
    if (comma == std::string::npos)
      break;
    start = comma + 1;
  }
  return any;
}

// ---------------------------------------------------------------------------- switch
#ifdef USE_SWITCH
void MaintenanceSwitch::write_state(bool state) {
  if (this->parent_ == nullptr)
    return;
  if (this->parent_->request_maintenance(state)) {
    this->publish_state(state);
  } else {
    this->publish_state(this->parent_->maintenance());
  }
}

void MaintenanceSwitch::dump_config() { LOG_SWITCH("", "Mode maintenance", this); }
#endif

}  // namespace cm1_bridge
}  // namespace esphome
