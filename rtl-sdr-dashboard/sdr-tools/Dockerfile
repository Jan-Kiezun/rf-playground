FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    sox \
    ffmpeg \
    multimon-ng \
    cmake \
    git \
    build-essential \
    pkg-config \
    wget \
    unzip \
    libusb-1.0-0-dev \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install RTL-SDR Blog V4 fork of librtlsdr.
# The standard Debian rtl-sdr package does NOT support the R828D tuner used
# in the RTL-SDR Blog V4 dongle.  This fork adds V4 support.
# https://github.com/rtlsdrblog/rtl-sdr-blog
RUN git clone https://github.com/rtlsdrblog/rtl-sdr-blog.git /tmp/rtl-sdr-blog \
    && cd /tmp/rtl-sdr-blog \
    && mkdir build && cd build \
    && cmake .. -DDETACH_KERNEL_DRIVER=ON -DINSTALL_UDEV_RULES=ON \
    && make -j$(nproc) && make install \
    && ldconfig \
    && rm -rf /tmp/rtl-sdr-blog

# Install rtl_433
RUN git clone https://github.com/merbanan/rtl_433.git /tmp/rtl_433 \
    && cd /tmp/rtl_433 \
    && mkdir build && cd build \
    && cmake .. && make -j$(nproc) && make install \
    && rm -rf /tmp/rtl_433

# Install dump1090
RUN git clone https://github.com/antirez/dump1090.git /opt/dump1090 \
    && cd /opt/dump1090 \
    && make \
    && ln -s /opt/dump1090/dump1090 /usr/local/bin/dump1090

# Install noaa-apt (optional - best-effort; log if unavailable at runtime)
RUN wget -q https://github.com/martinber/noaa-apt/releases/download/v1.4.1/noaa-apt-1.4.1-x86_64-linux-gnu-nogui.zip \
    -O /tmp/noaa-apt.zip \
    && cd /tmp && unzip -o noaa-apt.zip \
    && find /tmp -name 'noaa-apt*' -type f -executable -exec mv {} /usr/local/bin/noaa-apt \; \
    && chmod +x /usr/local/bin/noaa-apt \
    && rm -f /tmp/noaa-apt.zip \
    || echo "WARNING: noaa-apt installation failed - NOAA APT decoding will be unavailable"

# Create socket directory
RUN mkdir -p /var/run/sdr /tmp/hls

# NOTE: if the host kernel grabs the dongle before librtlsdr can, run:
#   sudo ./sdr-tools/setup-host.sh
# on the HOST to blacklist the dvb_usb_rtl28xxu module.

COPY start.sh /start.sh
RUN chmod +x /start.sh

# 1234 = rtl_tcp SDR stream, 8080 = health-check endpoint
EXPOSE 1234 8080

CMD ["/start.sh"]
