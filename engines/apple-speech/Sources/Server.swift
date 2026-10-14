// 小さな HTTP/1.1 の server (= Network framework)。 1 つの接続で 1 つの要求を受け、 答えたら閉じる。

import Foundation
import Network
import os

struct Response {
  let status: Int
  let body: Data
  var contentType = "application/json"

  static func json(_ status: Int, _ object: [String: Any]) -> Response {
    Response(status: status, body: (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8))
  }
}

final class Server: @unchecked Sendable {
  typealias Handler = @Sendable (RequestHead, Data) async -> Response

  private let listener: NWListener
  private let handler: Handler
  private let maxBodyBytes: Int
  private let queue = DispatchQueue(label: "apple-speech.server")

  /// host と port だけで待ち受ける (= 例えば 127.0.0.1 なら、 同じ機械からしか繋がらない)。
  init(host: String, port: UInt16, maxBodyBytes: Int, handler: @escaping Handler) throws {
    let parameters = NWParameters.tcp
    parameters.allowLocalEndpointReuse = true
    parameters.requiredLocalEndpoint = .hostPort(host: NWEndpoint.Host(host), port: NWEndpoint.Port(rawValue: port)!)
    listener = try NWListener(using: parameters)
    self.handler = handler
    self.maxBodyBytes = maxBodyBytes
  }

  /// 待ち受けを始め、 待ち受けられた時か失敗した時に返る。
  func start() async throws {
    try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, Error>) in
      // 待ち受けの状態は何度も変わるが、 返すのは最初の「待ち受けた」 か「失敗した」 の 1 回だけ
      let settled = OSAllocatedUnfairLock(initialState: false)
      listener.stateUpdateHandler = { state in
        switch state {
        case .ready, .failed: break
        default: return
        }
        guard settled.withLock({ already in defer { already = true }; return !already }) else { return }
        if case .failed(let error) = state { done.resume(throwing: error) } else { done.resume() }
      }
      listener.newConnectionHandler = { [weak self] connection in self?.serve(connection) }
      listener.start(queue: queue)
    }
  }

  private func serve(_ connection: NWConnection) {
    connection.start(queue: queue)
    receive(connection, Data())
  }

  private func receive(_ connection: NWConnection, _ buffer: Data) {
    connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] chunk, _, isComplete, error in
      guard let self else { return }
      var buffer = buffer
      if let chunk { buffer.append(chunk) }
      do {
        if let (head, bodyStart) = try HTTPHead.parse(buffer) {
          if head.contentLength > maxBodyBytes {
            return reply(connection, .json(413, ["error": "the body is larger than \(maxBodyBytes) bytes"]))
          }
          let body = buffer[bodyStart...]
          if body.count >= head.contentLength {
            let request = Data(body.prefix(head.contentLength))
            Task { self.reply(connection, await self.handler(head, request)) }
            return
          }
        }
      } catch let error as HTTPError {
        return reply(connection, .json(error.status, ["error": error.message]))
      } catch {
        return reply(connection, .json(400, ["error": "\(error)"]))
      }
      if error != nil || isComplete { connection.cancel(); return }
      receive(connection, buffer)
    }
  }

  private func reply(_ connection: NWConnection, _ response: Response) {
    let reason = HTTPURLResponse.localizedString(forStatusCode: response.status).capitalized
    var data = Data("HTTP/1.1 \(response.status) \(reason)\r\n".utf8)
    data.append(Data("Content-Type: \(response.contentType)\r\nContent-Length: \(response.body.count)\r\nConnection: close\r\n\r\n".utf8))
    data.append(response.body)
    connection.send(content: data, completion: .contentProcessed { _ in connection.cancel() })
  }
}
