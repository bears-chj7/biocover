"""UNO motor messages, separate from the four-column sensor CSV."""
import re


def angle_command(angle):
    if type(angle) is not int or not 0 <= angle <= 180:
        raise ValueError('각도는 0~180 사이의 정수여야 합니다.')
    return f'{angle}\n'.encode('ascii')


def parse_event(text):
    text = text.strip()
    if not text.startswith('#'):
        return None
    if text == '#READY':
        return {'kind': 'ready'}
    for prefix, kind in (('#ANGLE,', 'angle'), ('#STATUS,ANGLE,', 'status')):
        if text.startswith(prefix):
            value = text[len(prefix):]
            if kind == 'status' and value == 'NONE':
                return {'kind': kind, 'angle': None}
            if not re.fullmatch(r'\d{1,3}', value) or not 0 <= int(value) <= 180:
                raise ValueError('잘못된 UNO 각도 응답')
            return {'kind': kind, 'angle': int(value)}
    if text.startswith('#ERR,'):
        return {'kind': 'error', 'message': text[5:]}
    return {'kind': 'message', 'message': text}
