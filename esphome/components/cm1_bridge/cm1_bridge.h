#pragma once

#include <deque>
#include <memory>
#include <string>
#include <vector>

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/helpers.h"
#include "esphome/components/socket/socket.h"
#include "esphome/components/uart/uart.h"

#ifdef USE_BINARY_SENSOR
#include "esphome/components/binary_sensor/binary_sensor.h"
#endif
#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif
#ifdef USE_SWITCH
#include "esphome/components/switch/switch.h"
#endif

namespace esphome {
namespace cm1_bridge {

static const uint8_t PROTOCOL_VERSION = 1;

class MaintenanceSwitch;

/// Pont arbitré entre la logique embarquée, le moteur CM1 (UART) et des clients TCP.
class CM1Bridge : public Component, public uart::UARTDevice {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  void on_shutdown() override;
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  // --- configuration (codegen)
  void set_port(uint16_t port) { this->port_ = port; }
  void set_max_clients(uint8_t n) { this->max_clients_ = n; }
  void set_min_spacing(uint32_t ms) { this->min_spacing_ms_ = ms; }
  void set_maintenance_timeout(uint32_t s) { this->maint_timeout_ms_ = s * 1000UL; }
  void set_max_line_length(uint16_t n) { this->max_line_length_ = n; }
  void add_allowed_network(uint32_t network, uint32_t mask) { this->allowed_.push_back({network, mask}); }
#ifdef USE_BINARY_SENSOR
  void set_connected_sensor(binary_sensor::BinarySensor *s) { this->connected_sensor_ = s; }
#endif
#ifdef USE_SENSOR
  void set_connection_count_sensor(sensor::Sensor *s) { this->connection_count_sensor_ = s; }
#endif
#ifdef USE_SWITCH
  void set_maintenance_switch(switch_::Switch *s) { this->maintenance_switch_ = s; }
#endif
  void add_on_line_callback(std::function<void(const std::string &)> &&cb) { this->on_line_.add(std::move(cb)); }

  // --- interface pour la logique embarquée (lambdas du YAML)
  /// Envoie une ligne CML au moteur au nom de la logique locale (prioritaire).
  /// En mode maintenance, seules « * » et « *1 » passent. Retourne faux si refusée.
  bool send_local(const std::string &line);
  /// La logique locale signale qu'un mouvement ou le démarrage est en cours.
  void set_busy(bool busy);
  /// La logique locale signale que le moteur est en alarme.
  void set_alarm(bool alarm);
  /// Demande d'entrée ou de sortie du mode maintenance. Retourne vrai si accepté.
  bool request_maintenance(bool on);
  bool maintenance() const { return this->maintenance_; }
  bool busy() const { return this->busy_; }
  size_t client_count() const { return this->clients_.size(); }

 protected:
  struct Client {
    Client(std::unique_ptr<socket::Socket> s, std::string id, uint8_t index)
        : socket(std::move(s)), identifier(std::move(id)), index(index) {}
    std::unique_ptr<socket::Socket> socket;
    std::string identifier;
    uint8_t index;
    std::string rx;
    std::string pending;  // sortie en attente (socket pleine)
    bool disconnected{false};
    std::string name() const { return "C" + std::to_string(this->index); }
  };
  struct Network {
    uint32_t network;
    uint32_t mask;
  };
  struct TxItem {
    std::string line;
    std::string origin;
  };

  void accept_();
  void read_clients_();
  void flush_clients_();
  void cleanup_clients_();
  void read_uart_();
  void write_uart_();
  void handle_client_line_(Client &client, const std::string &line);
  void send_to_(Client &client, const std::string &text);
  void broadcast_(const std::string &text);
  void publish_sensors_();
  void set_maintenance_(bool on);
  bool ip_allowed_(uint32_t ip) const;
  std::string state_line_() const;
  static bool is_read_only_(const std::string &line);
  static std::string trim_(const std::string &s);

  uint16_t port_{6638};
  uint8_t max_clients_{4};
  uint32_t min_spacing_ms_{3};
  uint32_t maint_timeout_ms_{60000};
  uint16_t max_line_length_{120};
  std::vector<Network> allowed_;

  std::unique_ptr<socket::Socket> socket_;
  std::vector<Client> clients_;
  uint8_t next_client_index_{1};

  std::string rx_line_;
  std::deque<TxItem> tx_local_;
  std::deque<TxItem> tx_clients_;
  uint32_t last_tx_ms_{0};
  uint32_t next_tx_delay_ms_{0};

  bool maintenance_{false};
  bool busy_{false};
  bool alarm_{false};
  bool last_published_busy_{false};
  uint32_t no_client_since_{0};

  CallbackManager<void(const std::string &)> on_line_;
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *connected_sensor_{nullptr};
#endif
#ifdef USE_SENSOR
  sensor::Sensor *connection_count_sensor_{nullptr};
#endif
#ifdef USE_SWITCH
  switch_::Switch *maintenance_switch_{nullptr};
#endif
};

class LineTrigger : public Trigger<std::string> {
 public:
  explicit LineTrigger(CM1Bridge *parent) {
    parent->add_on_line_callback([this](const std::string &x) { this->trigger(x); });
  }
};

#ifdef USE_SWITCH
class MaintenanceSwitch : public switch_::Switch, public Component {
 public:
  void set_parent(CM1Bridge *parent) { this->parent_ = parent; }
  void setup() override { this->publish_state(false); }
  void dump_config() override;

 protected:
  void write_state(bool state) override;
  CM1Bridge *parent_{nullptr};
};
#endif

}  // namespace cm1_bridge
}  // namespace esphome
