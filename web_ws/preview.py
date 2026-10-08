"""Robot-free design preview. Run separately from run.py; never imports ROS."""
import argparse
import config


def create_preview_app():
    # Set before app imports the diary provider. Production run.py is unchanged.
    config.USE_FAKE = True
    config.HOST = '127.0.0.1'
    from bridge.app import create_app
    from bridge import state
    state.patch(mission='IDLE', battery={'percent': 87, 'charging': False,
                                      'ready': True, 'ready_pct': 20})
    app = create_app()

    @app.after_request
    def label_preview(response):
        if response.mimetype == 'text/html':
            response.direct_passthrough = False
            html = response.get_data(as_text=True)
            import re
            html = re.sub(r'(<body[^>]*>)', r'\1<div class="preview-banner">디자인 미리보기 · 예시 데이터이며 로봇에 명령을 보내지 않습니다.</div>', html, count=1)
            html = html.replace('</head>', '<script>window.ODI_PREVIEW = true;</script></head>')
            html = html.replace('</body>', '''<script>
            document.addEventListener('click', function(event) {
                const target = event.target.closest('a, button');
                if (!target) return;
                const nav = target.dataset.nav;
                const action = target.dataset.dashboardAction;
                const normal = target.id === 'normalBtn' || nav === 'normal' || action === 'normal';
                const explore = target.id === 'startBtn' || target.classList.contains('hero-cta') || nav === 'explore' || action === 'explore';
                const home = target.id === 'normalStop' || target.id === 'stopBtn' || nav === 'home';
                if (normal || explore || home) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    location.href = normal ? '/?screen=NORMAL' : explore ? '/?screen=EXPLORING' : '/';
                    return;
                }
                if (target.tagName !== 'BUTTON') return;
                event.preventDefault();
                event.stopImmediatePropagation();
                document.querySelector('.preview-banner').textContent =
                    '미리보기에서는 명령을 실행하지 않아요. 화면과 일기만 둘러볼 수 있어요.';
            }, true);
            </script></body>''')
            response.set_data(html)
        return response

    @app.before_request
    def block_commands():
        from flask import request, jsonify
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return jsonify(error='디자인 미리보기에서는 로봇 명령을 실행하지 않습니다.'), 503

    @app.get('/preview/camera.svg')
    def sample_camera():
        from flask import Response
        return Response('''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">
          <rect width="800" height="450" fill="#ece8dc"/>
          <path d="M0 285H800V450H0Z" fill="#d7ccba"/>
          <path d="M0 285H800M240 285L160 450M560 285L640 450" stroke="#c5b99f" fill="none"/>
          <rect x="330" y="177" width="130" height="110" rx="12" fill="#f2c959"/>
          <ellipse cx="395" cy="180" rx="65" ry="18" fill="#ffe596"/>
          <path d="M460 202H483Q512 232 483 254H460" fill="none" stroke="#f2c959" stroke-width="15"/>
          <rect x="305" y="145" width="220" height="165" rx="5" stroke="#4d998c" stroke-width="3" fill="none" stroke-dasharray="10 6"/>
          <text x="24" y="38" font-family="sans-serif" font-size="18" fill="#655d4e">PREVIEW · SAMPLE CAMERA</text>
          <text x="306" y="133" font-family="sans-serif" font-size="18" fill="#386c62">cup · example</text>
        </svg>''', mimetype='image/svg+xml')

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    app = create_preview_app()
    app.run(host=config.HOST, port=args.port, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()

