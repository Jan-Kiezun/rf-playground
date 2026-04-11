FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    rtl-sdr \
    librtlsdr-dev \
    sox \
    ffmpeg \
    multimon-ng \
    cmake \
    git \
    build-essential \
    pkg-config \
    wget \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

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

# Blacklist conflicting kernel modules (document only - actual blacklisting must be done on host)
# echo "blacklist dvb_usb_rtl28xxu" >> /etc/modprobe.d/rtlsdr.conf

EXPOSE 1234

CMD ["rtl_tcp", "-a", "0.0.0.0", "-p", "1234"]
