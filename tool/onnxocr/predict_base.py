from onnxruntime import InferenceSession, SessionOptions, get_available_providers

from tool.log import CUS_LOGGER


class PredictBase:
    def __init__(self, cpu=False):
        self.cpu = cpu

    def get_onnx_session(self, model_dir, use_gpu):
        if self.cpu:
            providers = ['CPUExecutionProvider']
        else:
            providers = get_available_providers()
        sess_options = SessionOptions()
        onnx_session = InferenceSession(model_dir, providers=providers, sess_options=sess_options)

        return onnx_session

    def safe_run(self, session, output_names, input_feed):
        """
        Wrapper for session.run() that handles DML encoding errors.
        DML provider error messages may contain non-UTF-8 bytes, which
        onnxruntime fails to decode, raising UnicodeDecodeError instead
        of a proper exception. Extract and log the real DML error, then retry.
        """
        try:
            return session.run(output_names, input_feed)
        except UnicodeDecodeError as e:
            raw_bytes = e.object if isinstance(e.object, bytes) else b''
            # Only keep ASCII portion of the DML error — the garbled tail is junk
            safe_msg = raw_bytes.decode('ascii', errors='backslashreplace')
            CUS_LOGGER.error(f"DML执行失败, 原始错误:\n{safe_msg}")
            try:
                return session.run(output_names, input_feed)
            except UnicodeDecodeError:
                CUS_LOGGER.warning("DML重试仍失败, 回退到CPU执行本次推理")
                cpu_session = InferenceSession(session._model_path, providers=['CPUExecutionProvider'])
                return cpu_session.run(output_names, input_feed)

    def get_output_name(self, onnx_session):
        """
        output_name = onnx_session.get_outputs()[0].name
        :param onnx_session:
        :return:
        """
        output_name = []
        for node in onnx_session.get_outputs():
            output_name.append(node.name)
        return output_name

    def get_input_name(self, onnx_session):
        """
        input_name = onnx_session.get_inputs()[0].name
        :param onnx_session:
        :return:
        """
        input_name = []
        for node in onnx_session.get_inputs():
            input_name.append(node.name)
        return input_name

    def get_input_feed(self, input_name, image_numpy):
        """
        input_feed={self.input_name: image_numpy}
        :param input_name:
        :param image_numpy:
        :return:
        """
        input_feed = {}
        for name in input_name:
            input_feed[name] = image_numpy
        return input_feed
