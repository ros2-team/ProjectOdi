"""Robot-free design preview. Run separately from run.py; never imports ROS."""
import argparse
import config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    # Set before app imports the diary provider. Production run.py is unchanged.
    config.USE_FAKE = True
    config.HOST = '127.0.0.1'
    config.PORT = args.port
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
            html = html.replace('</body>', '''<script>
            document.addEventListener('click', function(event) {
                const button = event.target.closest('button');
                if (!button) return;
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

    app.run(host=config.HOST, port=config.PORT, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()
