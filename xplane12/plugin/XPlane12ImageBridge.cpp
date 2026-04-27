#include "XPLM/XPLMDefs.h"
#include "XPLM/XPLMDisplay.h"
#include "XPLM/XPLMGraphics.h"
#include "XPLM/XPLMPlugin.h"
#include "XPLM/XPLMProcessing.h"
#include "XPLM/XPLMUtilities.h"

#include <GL/gl.h>

#include <algorithm>
#include <cstring>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

constexpr char kPluginName[] = "XPlane12ImageBridge";
constexpr char kPluginSignature[] = "org.agaii.xplane12.imagebridge";
constexpr char kPluginDescription[] = "Exports X-Plane 12 radar and avionics imagery from in-process callbacks.";
constexpr float kCaptureIntervalSeconds = 1.0F;
constexpr float kFlushIntervalSeconds = 0.5F;

struct ArtifactBuffer {
    std::string slug;
    int width = 0;
    int height = 0;
    std::vector<unsigned char> rgba;
    bool dirty = false;
    double updated_at = 0.0;
};

struct DeviceSpec {
    XPLMDeviceID device_id;
    const char* slug;
    XPLMAvionicsID handle = nullptr;
    double last_capture_at = 0.0;
};

std::vector<DeviceSpec> g_devices = {
    {xplm_device_GNS430_1, "gns430_1"},
    {xplm_device_GNS430_2, "gns430_2"},
    {xplm_device_GNS530_1, "gns530_1"},
    {xplm_device_GNS530_2, "gns530_2"},
    {xplm_device_Primus_PFD_1, "primus_pfd_1"},
    {xplm_device_Primus_MFD_1, "primus_mfd_1"},
    {xplm_device_Primus_MFD_3, "primus_mfd_3"},
    {xplm_device_Primus_MFD_2, "primus_mfd_2"},
    {xplm_device_Primus_PFD_2, "primus_pfd_2"},
};

std::unordered_map<std::string, ArtifactBuffer> g_artifacts;
std::mutex g_artifact_mutex;
double g_last_radar_capture_at = 0.0;
std::filesystem::path g_export_dir;

void debug_log(const std::string& message) {
    const std::string line = "[" + std::string(kPluginName) + "] " + message + "\n";
    XPLMDebugString(line.c_str());
}

std::filesystem::path plugin_output_dir() {
    if (!g_export_dir.empty()) {
        return g_export_dir;
    }

    const char* configured = std::getenv("XPLANE_IMAGE_EXPORT_DIR");
    if (configured != nullptr && configured[0] != '\0') {
        g_export_dir = configured;
    } else {
        char system_path[2048] = {};
        XPLMGetSystemPath(system_path);
        g_export_dir = std::filesystem::path(system_path) / "Output" / kPluginName;
    }

    std::error_code error;
    std::filesystem::create_directories(g_export_dir, error);
    if (error) {
        debug_log("failed to create export dir: " + error.message());
    } else {
        debug_log("export dir: " + g_export_dir.string());
    }
    return g_export_dir;
}

bool write_ppm_atomic(
    const std::filesystem::path& output_path,
    const std::vector<unsigned char>& rgba,
    int width,
    int height
) {
    if (width <= 0 || height <= 0) {
        return false;
    }
    if (rgba.size() < static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4U) {
        return false;
    }

    const std::filesystem::path temp_path = output_path.string() + ".tmp";
    std::ofstream stream(temp_path, std::ios::binary | std::ios::trunc);
    if (!stream.is_open()) {
        debug_log("failed to open temp artifact: " + temp_path.string());
        return false;
    }

    stream << "P6\n" << width << " " << height << "\n255\n";
    for (int row = height - 1; row >= 0; --row) {
        const std::size_t row_offset = static_cast<std::size_t>(row) * static_cast<std::size_t>(width) * 4U;
        for (int column = 0; column < width; ++column) {
            const std::size_t pixel_offset = row_offset + static_cast<std::size_t>(column) * 4U;
            stream.write(reinterpret_cast<const char*>(&rgba[pixel_offset]), 3);
        }
    }
    stream.close();

    if (!stream.good()) {
        debug_log("failed while writing temp artifact: " + temp_path.string());
        std::error_code cleanup_error;
        std::filesystem::remove(temp_path, cleanup_error);
        return false;
    }

    std::error_code rename_error;
    std::filesystem::rename(temp_path, output_path, rename_error);
    if (rename_error) {
        debug_log("failed to move artifact into place: " + rename_error.message());
        std::error_code cleanup_error;
        std::filesystem::remove(temp_path, cleanup_error);
        return false;
    }

    return true;
}

void queue_artifact(const std::string& slug, std::vector<unsigned char> rgba, int width, int height, double now) {
    std::lock_guard<std::mutex> lock(g_artifact_mutex);
    ArtifactBuffer& artifact = g_artifacts[slug];
    artifact.slug = slug;
    artifact.width = width;
    artifact.height = height;
    artifact.rgba = std::move(rgba);
    artifact.updated_at = now;
    artifact.dirty = true;
}

bool read_current_viewport_rgba(std::vector<unsigned char>& rgba, int& width, int& height) {
    GLint viewport[4] = {};
    glGetIntegerv(GL_VIEWPORT, viewport);
    width = viewport[2];
    height = viewport[3];
    if (width <= 32 || height <= 32) {
        return false;
    }

    rgba.resize(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4U);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    const GLenum error = glGetError();
    if (error != GL_NO_ERROR) {
        std::ostringstream message;
        message << "glReadPixels failed with error " << static_cast<unsigned int>(error);
        debug_log(message.str());
        return false;
    }
    return true;
}

bool read_texture_rgba(int texture_id, std::vector<unsigned char>& rgba, int& width, int& height) {
    if (texture_id <= 0) {
        return false;
    }

    GLint previous_binding = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &previous_binding);
    glBindTexture(GL_TEXTURE_2D, texture_id);

    GLint texture_width = 0;
    GLint texture_height = 0;
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &texture_width);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT, &texture_height);
    if (texture_width <= 32 || texture_height <= 32) {
        glBindTexture(GL_TEXTURE_2D, previous_binding);
        return false;
    }

    width = texture_width;
    height = texture_height;
    rgba.resize(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4U);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    const GLenum error = glGetError();
    glBindTexture(GL_TEXTURE_2D, previous_binding);
    if (error != GL_NO_ERROR) {
        std::ostringstream message;
        message << "glGetTexImage failed with error " << static_cast<unsigned int>(error);
        debug_log(message.str());
        return false;
    }
    return true;
}

void maybe_capture_radar(double now) {
    if ((now - g_last_radar_capture_at) < static_cast<double>(kCaptureIntervalSeconds)) {
        return;
    }

    g_last_radar_capture_at = now;
    for (const auto [texture_enum, slug] : {
             std::pair<XPLMTextureID, const char*>{xplm_Tex_Radar_Pilot, "weather_radar_pilot"},
             std::pair<XPLMTextureID, const char*>{xplm_Tex_Radar_Copilot, "weather_radar_copilot"},
         }) {
        std::vector<unsigned char> rgba;
        int width = 0;
        int height = 0;
        if (!read_texture_rgba(XPLMGetTexture(texture_enum), rgba, width, height)) {
            continue;
        }
        queue_artifact(slug, std::move(rgba), width, height, now);
    }
}

void capture_device(DeviceSpec& device) {
    const double now = static_cast<double>(XPLMGetElapsedTime());
    maybe_capture_radar(now);
    if ((now - device.last_capture_at) < static_cast<double>(kCaptureIntervalSeconds)) {
        return;
    }

    std::vector<unsigned char> rgba;
    int width = 0;
    int height = 0;
    if (!read_current_viewport_rgba(rgba, width, height)) {
        return;
    }

    device.last_capture_at = now;
    queue_artifact(device.slug, std::move(rgba), width, height, now);

}

DeviceSpec* find_device(XPLMDeviceID device_id) {
    for (auto& device : g_devices) {
        if (device.device_id == device_id) {
            return &device;
        }
    }
    return nullptr;
}

int avionics_after_draw_callback(XPLMDeviceID in_device_id, int in_is_before, void* in_refcon) {
    (void)in_refcon;
    if (in_is_before != 0) {
        return 1;
    }

    DeviceSpec* device = find_device(in_device_id);
    if (device != nullptr) {
        capture_device(*device);
    }
    return 1;
}

float flush_artifacts_flight_loop(float, float, int, void*) {
    const std::filesystem::path output_dir = plugin_output_dir();
    std::vector<ArtifactBuffer> dirty_artifacts;
    {
        std::lock_guard<std::mutex> lock(g_artifact_mutex);
        for (auto& [slug, artifact] : g_artifacts) {
            if (!artifact.dirty) {
                continue;
            }
            dirty_artifacts.push_back(artifact);
            artifact.dirty = false;
        }
    }

    for (const auto& artifact : dirty_artifacts) {
        const std::filesystem::path artifact_path = output_dir / (artifact.slug + ".ppm");
        write_ppm_atomic(artifact_path, artifact.rgba, artifact.width, artifact.height);
    }

    return kFlushIntervalSeconds;
}

void register_device_callbacks() {
    for (auto& device : g_devices) {
        XPLMCustomizeAvionics_t params = {};
        params.structSize = sizeof(params);
        params.deviceId = device.device_id;
        params.drawCallbackAfter = avionics_after_draw_callback;
        params.refcon = nullptr;
        device.handle = XPLMRegisterAvionicsCallbacksEx(&params);
        debug_log(
            std::string("register ")
            + device.slug
            + (device.handle != nullptr ? " ok" : " failed")
        );
    }
}

void unregister_device_callbacks() {
    for (auto& device : g_devices) {
        if (device.handle == nullptr) {
            continue;
        }
        XPLMUnregisterAvionicsCallbacks(device.handle);
        device.handle = nullptr;
    }
}

}  // namespace

PLUGIN_API int XPluginStart(char* out_name, char* out_signature, char* out_description) {
    std::strcpy(out_name, kPluginName);
    std::strcpy(out_signature, kPluginSignature);
    std::strcpy(out_description, kPluginDescription);
    plugin_output_dir();
    debug_log("start");
    return 1;
}

PLUGIN_API void XPluginStop(void) {
    XPLMUnregisterFlightLoopCallback(flush_artifacts_flight_loop, nullptr);
    unregister_device_callbacks();
    debug_log("stop");
}

PLUGIN_API int XPluginEnable(void) {
    register_device_callbacks();
    XPLMRegisterFlightLoopCallback(flush_artifacts_flight_loop, kFlushIntervalSeconds, nullptr);
    debug_log("enable");
    return 1;
}

PLUGIN_API void XPluginDisable(void) {
    XPLMUnregisterFlightLoopCallback(flush_artifacts_flight_loop, nullptr);
    unregister_device_callbacks();
    debug_log("disable");
}

PLUGIN_API void XPluginReceiveMessage(XPLMPluginID, int, void*) {
}
